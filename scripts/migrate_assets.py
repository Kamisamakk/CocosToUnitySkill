#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
migrate_assets.py
Phase 1: copy Cocos media/audio/font assets into a Unity project and generate
minimal Unity .meta files with sane import defaults. Also emits a manifest
mapping Cocos UUID -> Unity GUID so later phases can rewrite references.

Enhancements over v1:
  - Skips ignored directories (temp, library, build, node_modules, .git)
  - Extracts 9-slice border info from Cocos .meta files
  - Generates Sprite Atlas asset for each top-level folder under assets/
  - Supports --include and --exclude filters
  - Better error reporting and statistics

Usage:
  python migrate_assets.py --src <cocos>/assets --dst <unity>/Assets/_Ported \
      --manifest manifest.json [--dry-run] [--atlas]

Import defaults (Built-in RP + 2D Sprite):
  - Textures: TextureImporter, textureType=Sprite, pixelsPerUnit=100,
    filterMode=Bilinear, alphaIsTransparency=true, sRGBTexture=true.
  - Audio: AudioImporter, loadType=1 (CompressedInMemory), compressionFormat=1 (Vorbis).
  - Fonts: TrueTypeFontImporter defaults.
  - Generic: DefaultImporter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

IGNORE_DIRS = {"temp", "library", "build", "node_modules", ".git", "local",
               "__pycache__", ".vscode", ".idea", "dist"}

# SDK / ad content filter (shared module)
try:
    from sdk_filter import SdkFilter
except ImportError:
    SdkFilter = None

TEXTURE_EXT = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".webp", ".gif"}
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".m4a", ".aac"}
FONT_EXT = {".ttf", ".otf"}
PASSTHRU_EXT = {".json", ".atlas", ".skel", ".txt", ".xml", ".csv", ".shader",
                ".fnt", ".plist", ".tmx", ".tsx", ".effect", ".mtl"}

# Structural assets: these are NOT raw-copied — they need dedicated conversion
# scripts (convert_prefab.py, convert_scene.py, convert_anim.py) to produce
# Unity-native equivalents (.prefab YAML, .unity YAML, .anim YAML).
STRUCTURAL_EXT = {".scene", ".fire", ".prefab", ".anim"}

# Unity built-in / reserved GUIDs (partial list).
# These are hardcoded in the engine; we must NEVER generate a GUID that
# collides with them. Format: guid -> description.
UNITY_BUILTIN_GUIDS: Dict[str, str] = {
    "0000000000000000e000000000000000": "Built-in Arial font",
    "0000000000000000f000000000000000": "Built-in Extra resources",
    "0000000000000000d000000000000000": "Built-in Default Sprite",
    "0000000000000000b000000000000000": "Built-in Default Particle",
    "0000000000000000a000000000000000": "Built-in Default Avatar",
    "00000000000000001000000000000000": "Built-in Unity default resources",
    "00000000000000002000000000000000": "Built-in Unity default resources (2)",
    "00000000000000003000000000000000": "Built-in Unity default resources (3)",
    "00000000000000004000000000000000": "Built-in Unity editor resources",
    "00000000000000005000000000000000": "Built-in Unity editor resources (2)",
    "00000000000000006000000000000000": "Built-in Unity editor resources (3)",
}


def stable_guid(seed: str) -> str:
    """Produce a Unity-style 32-char hex GUID deterministically from a seed.

    Automatically avoids collisions with Unity built-in GUIDs by appending a
    salt suffix and rehashing if needed (probability ~0, but defense-in-depth).
    """
    guid = hashlib.md5(seed.encode("utf-8")).hexdigest()
    attempt = 0
    while guid in UNITY_BUILTIN_GUIDS and attempt < 8:
        attempt += 1
        guid = hashlib.md5(f"{seed}__salt{attempt}".encode("utf-8")).hexdigest()
    return guid


def find_cocos_uuid(meta_path: Path) -> Optional[str]:
    """Return the **primary** (top-level) UUID from a Cocos .meta file.

    For textures this is typically the Texture2D UUID.
    Use find_all_cocos_uuids() to also get SpriteFrame and other sub-asset UUIDs.
    """
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    for key in ("uuid", "__uuid__"):
        if isinstance(data.get(key), str):
            return data[key]

    def walk(obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("uuid", "__uuid__") and isinstance(v, str):
                    return v
                r = walk(v)
                if r:
                    return r
        elif isinstance(obj, list):
            for it in obj:
                r = walk(it)
                if r:
                    return r
        return None
    return walk(data)


def find_all_cocos_uuids(meta_path: Path) -> List[Dict[str, str]]:
    """Extract ALL UUIDs from a Cocos .meta file, including sub-asset UUIDs.

    Returns a list of dicts: [{"uuid": "xxx", "type": "main|spriteFrame|texture|..."}]
    The first entry is always the main asset UUID (same as find_cocos_uuid).

    Cocos .meta structure examples:

    3.x texture .meta:
    {
      "uuid": "aaa",           ← Texture2D main asset
      "subMetas": {
        "6c48a": {              ← SpriteFrame sub-asset (key = short hash)
          "uuid": "bbb",
          "subMetas": {}
        }
      }
    }

    2.x texture .meta:
    {
      "uuid": "aaa",
      "subMetas": {
        "hero": {               ← SpriteFrame (key = sprite name)
          "uuid": "bbb",
          "rawTextureUuid": "aaa"
        }
      }
    }
    """
    if not meta_path.is_file():
        return []
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []

    results: List[Dict[str, str]] = []
    seen: Set[str] = set()

    # 1. Main UUID (top-level)
    main_uuid = None
    for key in ("uuid", "__uuid__"):
        if isinstance(data.get(key), str):
            main_uuid = data[key]
            break

    if main_uuid:
        results.append({"uuid": main_uuid, "type": "main"})
        seen.add(main_uuid)

    # 2. Recursively collect all UUIDs from subMetas
    def collect_sub_uuids(obj: Any, depth: int = 0):
        if depth > 10:  # safety limit
            return
        if isinstance(obj, dict):
            sub_metas = obj.get("subMetas")
            if isinstance(sub_metas, dict):
                for sub_key, sub_val in sub_metas.items():
                    if isinstance(sub_val, dict):
                        sub_uuid = sub_val.get("uuid") or sub_val.get("__uuid__")
                        if isinstance(sub_uuid, str) and sub_uuid not in seen:
                            # Determine sub-asset type from its __type__ or key name
                            sub_type = sub_val.get("__type__", sub_key)
                            # Normalize common types
                            if "sprite" in sub_type.lower() or "sprite" in sub_key.lower():
                                sub_type = "spriteFrame"
                            elif "texture" in sub_type.lower():
                                sub_type = "texture"
                            else:
                                sub_type = f"sub:{sub_key}"
                            results.append({"uuid": sub_uuid, "type": sub_type})
                            seen.add(sub_uuid)
                        # Recurse into nested subMetas
                        collect_sub_uuids(sub_val, depth + 1)

    collect_sub_uuids(data)

    # 3. If no results at all, fall back to deep walk (same as find_cocos_uuid)
    if not results:
        def walk(obj: Any) -> Optional[str]:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("uuid", "__uuid__") and isinstance(v, str):
                        return v
                    r = walk(v)
                    if r:
                        return r
            elif isinstance(obj, list):
                for it in obj:
                    r = walk(it)
                    if r:
                        return r
            return None
        fallback = walk(data)
        if fallback:
            results.append({"uuid": fallback, "type": "main"})

    return results


def extract_9slice(meta_path: Path) -> Optional[Dict[str, int]]:
    """Extract 9-slice border data from Cocos .meta file."""
    if not meta_path.is_file():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None

    # 3.x: subMetas -> spriteFrame -> borderTop/Bottom/Left/Right
    # 2.x: borderTop, borderBottom, borderLeft, borderRight at top level or under subMetas
    def find_borders(obj):
        if isinstance(obj, dict):
            bt = obj.get("borderTop")
            if bt is not None and any(obj.get(k) is not None for k in ("borderBottom", "borderLeft", "borderRight")):
                return {
                    "top": int(obj.get("borderTop", 0)),
                    "bottom": int(obj.get("borderBottom", 0)),
                    "left": int(obj.get("borderLeft", 0)),
                    "right": int(obj.get("borderRight", 0)),
                }
            for v in obj.values():
                r = find_borders(v)
                if r:
                    return r
        elif isinstance(obj, list):
            for it in obj:
                r = find_borders(it)
                if r:
                    return r
        return None
    return find_borders(data)


def texture_meta(guid: str, border: Optional[Dict[str, int]] = None) -> str:
    # Convert border to Unity sprite border format: left, bottom, right, top
    if border and any(v > 0 for v in border.values()):
        border_str = f"{{x: {border.get('left', 0)}, y: {border.get('bottom', 0)}, z: {border.get('right', 0)}, w: {border.get('top', 0)}}}"
        sprite_mode = 1  # Single sprite with border
    else:
        border_str = "{x: 0, y: 0, z: 0, w: 0}"
        sprite_mode = 1

    return f"""fileFormatVersion: 2
guid: {guid}
TextureImporter:
  internalIDToNameTable: []
  externalObjects: {{}}
  serializedVersion: 11
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 1
    linearTexture: 0
    fadeOut: 0
    borderMipMap: 0
    mipMapsPreserveCoverage: 0
    alphaTestReferenceValue: 0.5
    mipMapFadeDistanceStart: 1
    mipMapFadeDistanceEnd: 3
  bumpmap:
    convertToNormalMap: 0
    externalNormalMap: 0
    heightScale: 0.25
    normalMapFilter: 0
  isReadable: 0
  streamingMipmaps: 0
  streamingMipmapsPriority: 0
  vTOnly: 0
  ignoreMasterTextureLimit: 0
  grayScaleToAlpha: 0
  generateCubemap: 6
  cubemapConvolution: 0
  seamlessCubemap: 0
  textureFormat: 1
  maxTextureSize: 2048
  textureSettings:
    serializedVersion: 2
    filterMode: 1
    aniso: 1
    mipBias: 0
    wrapU: 1
    wrapV: 1
    wrapW: 1
  nPOTScale: 0
  lightmap: 0
  compressionQuality: 50
  spriteMode: {sprite_mode}
  spriteExtrude: 1
  spriteMeshType: 1
  alignment: 0
  spritePivot: {{x: 0.5, y: 0.5}}
  spritePixelsToUnits: 100
  spriteBorder: {border_str}
  spriteGenerateFallbackPhysicsShape: 1
  alphaUsage: 1
  alphaIsTransparency: 1
  spriteTessellationDetail: -1
  textureType: 8
  textureShape: 1
  singleChannelComponent: 0
  flipbookRows: 1
  flipbookColumns: 1
  maxTextureSizeSet: 0
  compressionQualitySet: 0
  textureFormatSet: 0
  ignorePngGamma: 0
  applyGammaDecoding: 0
  platformSettings:
  - serializedVersion: 3
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 2048
    resizeAlgorithm: 0
    textureFormat: -1
    textureCompression: 1
    compressionQuality: 50
    crunchedCompression: 0
    allowsAlphaSplitting: 0
    overridden: 0
    androidETC2FallbackOverride: 0
    forceMaximumCompressionQuality_BC6H_BC7: 0
  spriteSheet:
    serializedVersion: 2
    sprites: []
    outline: []
    physicsShape: []
    bones: []
    spriteID: ""
    internalID: 0
    vertices: []
    indices:
    edges: []
    weights: []
    secondaryTextures: []
    nameFileIdTable: {{}}
  spritePackingTag:
  pSDRemoveMatte: 0
  pSDShowRemoveMatteOption: 0
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def audio_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
AudioImporter:
  externalObjects: {{}}
  serializedVersion: 6
  defaultSettings:
    loadType: 1
    sampleRateSetting: 0
    sampleRateOverride: 44100
    compressionFormat: 1
    quality: 1
    conversionMode: 0
  platformSettingOverrides: {{}}
  forceToMono: 0
  normalize: 1
  preloadAudioData: 0
  loadInBackground: 0
  ambisonic: 0
  3D: 0
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def default_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
DefaultImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def font_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
TrueTypeFontImporter:
  externalObjects: {{}}
  serializedVersion: 4
  fontSize: 16
  forceTextureCase: -2
  characterSpacing: 0
  characterPadding: 1
  includeFontData: 1
  fontName:
  fontNames: []
  fallbackFontReferences: []
  customCharacters:
  fontRenderingMode: 0
  ascentCalculationMode: 1
  useLegacyBoundsCalculation: 0
  shouldRoundAdvanceValue: 1
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def folder_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
folderAsset: yes
DefaultImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def sprite_atlas_asset(atlas_name: str, guid: str, sprite_folder: str) -> str:
    """Generate a Unity SpriteAtlas .spriteatlas file content."""
    return f"""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!687078895 &4343727234628468602
SpriteAtlas:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {{fileID: 0}}
  m_PrefabInstance: {{fileID: 0}}
  m_PrefabAsset: {{fileID: 0}}
  m_Name: {atlas_name}
  m_EditorData:
    serializedVersion: 2
    textureSettings:
      serializedVersion: 2
      anisoLevel: 1
      compressionQuality: 50
      maxTextureSize: 2048
      textureCompression: 0
      filterMode: 1
      generateMipMaps: 0
      readable: 0
      crunchedCompression: 0
      sRGB: 1
    platformSettings: []
    packingSettings:
      serializedVersion: 2
      padding: 4
      blockOffset: 1
      allowAlphaSplitting: 0
      enableRotation: 0
      enableTightPacking: 0
      enableAlphaDilation: 0
    secondaryTextureSettings: []
    variantMultiplier: 1
    packables:
    - {{fileID: 102900000, guid: {guid}, type: 3}}
    bindAsDefault: 1
    isAtlasV2: 0
    cachedData: {{fileID: 0}}
  m_MasterAtlas: {{fileID: 0}}
  m_PackedSprites: []
  m_PackedSpriteNamesToIndex: []
  m_RenderDataMap: {{}}
  m_Tag: {atlas_name}
  m_IsVariant: 0
"""


def meta_for(ext: str, guid: str, border: Optional[Dict[str, int]] = None) -> str:
    if ext in TEXTURE_EXT:
        return texture_meta(guid, border)
    if ext in AUDIO_EXT:
        return audio_meta(guid)
    if ext in FONT_EXT:
        return font_meta(guid)
    return default_meta(guid)


def _should_skip_dir(name: str) -> bool:
    return name.lower() in IGNORE_DIRS


def migrate(src: Path, dst: Path, dry_run: bool, generate_atlas: bool,
            strip_sdk: bool = False) -> Dict[str, Any]:
    manifest: Dict[str, Any] = {"version": 2, "entries": [], "src": str(src), "dst": str(dst)}
    copied = skipped = errors = 0
    structural_skipped: Dict[str, int] = {}  # ext -> count
    atlas_folders: Set[str] = set()  # top-level folders for atlas generation

    # SDK / ad filter
    sdk_filt = SdkFilter() if (strip_sdk and SdkFilter) else None
    sdk_excluded: List[Dict[str, Any]] = []

    for dirpath, dirnames, filenames in os.walk(src):
        # Filter ignored directories
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        # Filter SDK directories at walk level (prune entire subtrees)
        if sdk_filt:
            dirnames[:] = [d for d in dirnames if not sdk_filt.should_exclude_dir(d)]
        dp = Path(dirpath)

        for fname in filenames:
            path = dp / fname
            ext = path.suffix.lower()
            if ext == ".meta":
                continue
            # Skip .d.ts and other non-asset files
            if fname.endswith(".d.ts") or ext in (".ts", ".js"):
                continue  # scripts handled in Phase 3

            # --- SDK / ad filter ---
            if sdk_filt:
                rel_check = path.relative_to(src)
                category = sdk_filt.classify(rel_check)
                if category:
                    sdk_excluded.append({
                        "path": rel_check.as_posix(),
                        "category": category,
                        "ext": ext,
                    })
                    continue

            # Skip structural assets — these need dedicated conversion scripts
            # (convert_prefab.py / convert_anim.py) to produce Unity-native files
            if ext in STRUCTURAL_EXT:
                structural_skipped[ext] = structural_skipped.get(ext, 0) + 1
                # Still record in manifest for reference tracking (but mark as structural)
                rel = path.relative_to(src)
                cocos_uuid = find_cocos_uuid(path.with_suffix(path.suffix + ".meta"))
                seed = cocos_uuid or f"cocos2unity:{rel.as_posix()}"
                guid = stable_guid(seed)
                manifest["entries"].append({
                    "src": rel.as_posix(),
                    "dst": None,  # not raw-copied; converted by dedicated script
                    "cocos_uuid": cocos_uuid,
                    "unity_guid": guid,
                    "kind": ext.lstrip("."),
                    "structural": True,
                })
                skipped += 1
                continue

            rel = path.relative_to(src)
            target = dst / rel
            target_meta = target.with_suffix(target.suffix + ".meta")

            cocos_uuid = find_cocos_uuid(path.with_suffix(path.suffix + ".meta"))
            seed = cocos_uuid or f"cocos2unity:{rel.as_posix()}"
            guid = stable_guid(seed)

            # Extract 9-slice border for textures
            border = None
            if ext in TEXTURE_EXT:
                border = extract_9slice(path.with_suffix(path.suffix + ".meta"))
                # Track atlas folders
                if generate_atlas and len(rel.parts) > 1:
                    atlas_folders.add(rel.parts[0])

            entry = {
                "src": rel.as_posix(),
                "dst": rel.as_posix(),
                "cocos_uuid": cocos_uuid,
                "unity_guid": guid,
                "kind": ext.lstrip("."),
            }
            if border and any(v > 0 for v in border.values()):
                entry["border_9slice"] = border
            manifest["entries"].append(entry)

            # ---- Sub-asset UUID registration (SpriteFrame, etc.) ----
            # Cocos scenes reference SpriteFrame UUIDs, not Texture2D UUIDs.
            # We map every sub-asset UUID to the SAME Unity texture GUID so that
            # _resolve_sprite_guid() can find the texture when looking up a
            # SpriteFrame UUID from the scene JSON.
            if ext in TEXTURE_EXT:
                all_uuids = find_all_cocos_uuids(path.with_suffix(path.suffix + ".meta"))
                for sub in all_uuids:
                    sub_uuid = sub["uuid"]
                    if sub_uuid == cocos_uuid:
                        continue  # main UUID already registered above
                    manifest["entries"].append({
                        "src": rel.as_posix(),
                        "dst": rel.as_posix(),
                        "cocos_uuid": sub_uuid,
                        "unity_guid": guid,  # same Unity GUID as the texture
                        "kind": f"{ext.lstrip('.')}.{sub['type']}",
                        "sub_asset_of": cocos_uuid,
                    })

            if dry_run:
                copied += 1
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                target_meta.write_text(meta_for(ext, guid, border), encoding="utf-8")
                copied += 1
            except Exception as e:
                print(f"  ERROR copying {rel}: {e}", file=sys.stderr)
                errors += 1

    # Generate folder .meta files to stabilize GUIDs
    if not dry_run:
        _generate_folder_metas(dst)

    # Generate sprite atlases
    atlases_created = 0
    if generate_atlas and not dry_run and atlas_folders:
        atlas_dir = dst / "_SpriteAtlases"
        atlas_dir.mkdir(parents=True, exist_ok=True)
        for folder_name in sorted(atlas_folders):
            folder_path = dst / folder_name
            if folder_path.is_dir():
                atlas_name = f"Atlas_{folder_name}"
                folder_guid = stable_guid(f"cocos2unity:folder:{folder_name}")
                atlas_file = atlas_dir / f"{atlas_name}.spriteatlas"
                atlas_file.write_text(sprite_atlas_asset(atlas_name, folder_guid, folder_name), encoding="utf-8")
                atlas_meta = atlas_file.with_suffix(".spriteatlas.meta")
                atlas_meta.write_text(default_meta(stable_guid(f"cocos2unity:atlas:{atlas_name}")), encoding="utf-8")
                atlases_created += 1

    # --- GUID collision detection ---
    collisions = validate_guid_collisions(manifest["entries"])
    manifest["stats"] = {
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
        "atlases_created": atlases_created,
        "has_9slice": sum(1 for e in manifest["entries"] if e.get("border_9slice")),
        "structural_skipped": structural_skipped,
        "guid_collisions": len(collisions),
        "sdk_excluded": len(sdk_excluded),
    }
    if collisions:
        manifest["guid_collisions"] = collisions
    if sdk_excluded:
        manifest["sdk_excluded_details"] = sdk_excluded[:100]
        by_cat: Dict[str, int] = {}
        for item in sdk_excluded:
            cat = item.get("category", "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        manifest["stats"]["sdk_excluded_by_category"] = by_cat
        print(f"  SDK/ad content excluded: {len(sdk_excluded)} assets {by_cat}")
    return manifest


# ---------------------------------------------------------------------------
# GUID safety: collision detection (built-in GUID table is at module top)
# ---------------------------------------------------------------------------


def validate_guid_collisions(entries: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Detect GUID collisions among generated entries AND with Unity built-ins.

    Returns a list of collision records (empty if no collisions).
    """
    collisions: List[Dict[str, str]] = []
    seen: Dict[str, str] = {}  # guid -> src path

    for entry in entries:
        guid = entry.get("unity_guid")
        if not guid:
            continue
        src = entry.get("src", "<unknown>")

        # Check against Unity built-in GUIDs
        if guid in UNITY_BUILTIN_GUIDS:
            desc = UNITY_BUILTIN_GUIDS[guid]
            collisions.append({
                "guid": guid,
                "src_a": src,
                "src_b": f"[Unity built-in: {desc}]",
                "type": "builtin_collision",
            })
            print(f"  ⚠️ GUID collision with Unity built-in! {src} -> {guid} ({desc})",
                  file=sys.stderr)

        # Check against other entries
        if guid in seen:
            collisions.append({
                "guid": guid,
                "src_a": seen[guid],
                "src_b": src,
                "type": "internal_collision",
            })
            print(f"  ⚠️ GUID collision between entries: {seen[guid]} vs {src} -> {guid}",
                  file=sys.stderr)
        else:
            seen[guid] = src

    return collisions


def _generate_folder_metas(root: Path):
    """Generate .meta files for directories to stabilize Unity folder GUIDs."""
    for dirpath, dirnames, _ in os.walk(root):
        dp = Path(dirpath)
        if dp == root:
            continue
        meta_file = dp.with_suffix(dp.suffix + ".meta") if dp.suffix else Path(str(dp) + ".meta")
        # Actually Unity folder metas go NEXT to the folder, not inside it
        folder_meta_path = dp.parent / (dp.name + ".meta")
        if not folder_meta_path.exists():
            guid = stable_guid(f"cocos2unity:folder:{dp.relative_to(root).as_posix()}")
            folder_meta_path.write_text(folder_meta(guid), encoding="utf-8")


def main() -> int:
    # Ensure utf-8 output on Windows (for Chinese path names etc.)
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Phase 1: Migrate Cocos assets to Unity with .meta generation")
    ap.add_argument("--src", required=True, help="Cocos assets/ directory")
    ap.add_argument("--dst", required=True, help="Unity Assets/_Ported/ directory")
    ap.add_argument("--manifest", required=True, help="Output manifest JSON path")
    ap.add_argument("--dry-run", action="store_true", help="Preview without copying")
    ap.add_argument("--atlas", action="store_true", help="Generate SpriteAtlas per top-level folder")
    ap.add_argument("--strip-sdk", action="store_true",
                    help="Exclude SDK/ad/analytics assets from migration")
    args = ap.parse_args()

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    if not src.is_dir():
        print(f"ERROR: src not a directory: {src}", file=sys.stderr)
        return 2
    if not args.dry_run:
        dst.mkdir(parents=True, exist_ok=True)

    manifest = migrate(src, dst, args.dry_run, args.atlas, strip_sdk=args.strip_sdk)
    mf = Path(args.manifest)
    mf.parent.mkdir(parents=True, exist_ok=True)
    mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = manifest["stats"]
    mode = "DRY-RUN " if args.dry_run else ""
    structural = stats.get("structural_skipped", {})
    structural_info = " ".join(f"{k}={v}" for k, v in structural.items()) if structural else "none"
    print(f"{mode}OK copied={stats['copied']} skipped={stats['skipped']} errors={stats['errors']} "
          f"9slice={stats['has_9slice']} atlases={stats['atlases_created']} "
          f"guid_collisions={stats.get('guid_collisions', 0)} manifest={mf}")
    if structural:
        print(f"   structural assets (need convert_prefab.py): {structural_info}")
    guid_collisions = stats.get("guid_collisions", 0)
    if guid_collisions > 0:
        print(f"   ⚠️  {guid_collisions} GUID collision(s) detected! Check manifest 'guid_collisions' for details.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
