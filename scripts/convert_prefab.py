#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
convert_prefab.py  v3
Phase 2+: batch-convert ALL Cocos Creator prefabs (.prefab) and scenes
(.scene / .fire) into Unity-native files (.prefab YAML / .unity YAML).

v3 changes:
  - Full property-level mapping for all major components
  - Cocos color (0-255) → Unity color (0-1) automatic conversion
  - m_Script GUID references for Unity built-in UI components
  - Canvas auto-injects CanvasScaler + GraphicRaycaster
  - Sprite/Font references resolved through manifest uuid→guid
  - Camera, AudioSource, Physics2D, LayoutGroup real fields
  - UI layer (5) auto-set for UI nodes

Usage:
  # Batch mode (recommended): convert ALL prefabs and scenes at once
  python convert_prefab.py \\
    --src <cocos-root>/assets \\
    --dst <unity-root>/Assets/_Ported \\
    --manifest manifest.json \\
    [--convert-pos] [--ppu 100]

  # Single file mode
  python convert_prefab.py \\
    --src-file <file.prefab|file.scene|file.fire> \\
    --dst-file <output.prefab|output.unity> \\
    --manifest manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reuse convert_scene logic
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from convert_scene import (
    load_cocos, detect_format, build_plan_3x, build_plan_2x, ensure_script_mappings
)


IGNORE_DIRS = {"temp", "library", "build", "node_modules", ".git", "local",
               "__pycache__", ".vscode", ".idea", "dist"}

# ---------------------------------------------------------------------------
# Unity built-in script GUIDs (from UnityEngine.UI.dll / UnityEngine.dll)
# These are stable across Unity 2019-2022 Built-in pipeline.
# ---------------------------------------------------------------------------
BUILTIN_SCRIPT_GUIDS: Dict[str, Tuple[str, str]] = {
    # (fileID, guid) — fileID is the script's persistent ID inside the DLL
    "UnityEngine.UI.Image":       ("11500000", "fe87c0e1cc204ed48ad3b37840f39efc"),
    "UnityEngine.UI.Text":        ("11500000", "5f7201a12d95ffc409449d95f23cf332"),
    "UnityEngine.UI.Button":      ("11500000", "4e29b1a8efbd4b44bb3f3716e73f07ff"),
    "UnityEngine.UI.Toggle":      ("11500000", "9085046f02f69544eb97fd06b6048fe2"),
    "UnityEngine.UI.Slider":      ("11500000", "67db9e8f0e2ae9c40bc1e2b64352a6b4"),
    "UnityEngine.UI.Scrollbar":   ("11500000", "2a4db7a114972834c8e4117be1d82ba3"),
    "UnityEngine.UI.ScrollRect":  ("11500000", "1aa08ab6e0800fa44ae55d278d1423e3"),

    "UnityEngine.UI.InputField":  ("11500000", "d199490a83bb2b844b9695cbf13b01ef"),
    "UnityEngine.UI.RectMask2D":  ("11500000", "3312d7739989d2b4e91e6319e9a96d76"),
    "UnityEngine.UI.Outline":     ("11500000", "e19747de3f5aca642ab2be37e372fb86"),
    "UnityEngine.UI.Shadow":      ("11500000", "cfabb0440166ab443bba8876756fdfa9"),
    "SpriteMask":                 ("11500000", "0000000000000000d000000000000000"),



    "UnityEngine.UI.ToggleGroup": ("11500000", "2fafe2cfe61f6974895a912c3755e8f1"),
    "UnityEngine.UI.RawImage":    ("11500000", "1344c3c82d62a2a41a3576d8abb8e3ea"),
    "HorizontalLayoutGroup":      ("11500000", "30649d3a9faa99c48a7b1166b86bf2a0"),
    "VerticalLayoutGroup":        ("11500000", "59f8146938fff824cb5fd77236b75775"),
    "GridLayoutGroup":            ("11500000", "8a8695521f0d02e499659fee002a26c2"),
    "CanvasScaler":               ("11500000", "0cd44c1031e13a943bb63640046fad76"),
    "GraphicRaycaster":           ("11500000", "dc42784cf147c0c48a680349fa168899"),
}

# ---------------------------------------------------------------------------
# Unity built-in default asset references
# These are used when Cocos doesn't specify a material or the asset is missing.
# ---------------------------------------------------------------------------
# Unity UI default material — used by Image, Text, RawImage etc.
# This is the "Default UI Material" built into UnityEngine.UI
UNITY_DEFAULT_UI_MATERIAL = "{fileID: 10754, guid: 0000000000000000e000000000000000, type: 0}"
# Unity Sprites-Default material — used by SpriteRenderer
UNITY_SPRITES_DEFAULT_MATERIAL = "{fileID: 10754, guid: 0000000000000000f000000000000000, type: 0}"
# Unity Default-Material (3D) — standard opaque
UNITY_DEFAULT_MATERIAL = "{fileID: 10303, guid: 0000000000000000e000000000000000, type: 0}"
# Unity built-in Arial font
UNITY_DEFAULT_FONT = "{fileID: 10102, guid: 0000000000000000e000000000000000, type: 0}"

# Unity class IDs for native (non-script) components
NATIVE_CLASS_IDS: Dict[str, int] = {
    "Canvas":            223,
    "Camera":             20,
    "SpriteRenderer":    212,
    "AudioSource":        82,
    "Animator":           95,
    "ParticleSystem":    198,
    "Rigidbody2D":        50,
    "BoxCollider2D":      61,
    "CircleCollider2D":   58,
    "PolygonCollider2D":  60,
}

# Mapping of C# class names to their Unity GUIDs (populated at runtime)
_script_guid_map: Dict[str, str] = {}


def _scan_script_guids(unity_assets_dir: Path):
    """Scan Unity Assets directory for .cs.meta files and build a name -> guid map."""
    global _script_guid_map
    if not unity_assets_dir.exists():
        return
    
    print(f"Scanning for script GUIDs in {unity_assets_dir}...")
    count = 0
    for meta_file in unity_assets_dir.rglob("*.cs.meta"):
        try:
            content = meta_file.read_text(encoding="utf-8")
            guid = ""
            for line in content.splitlines():
                if line.startswith("guid:"):
                    guid = line.split(":")[1].strip()
                    break
            
            if guid:
                class_name = meta_file.stem.replace(".cs", "")
                _script_guid_map[class_name] = guid
                count += 1
        except Exception as e:
            print(f"  Warning: failed to read {meta_file.name}: {e}")
    
    print(f"  Found {count} script GUIDs.")


# Module-level name map (set during plan_to_unity_yaml, used by _resolve_sprite_guid)

_global_name_map: Dict[str, str] = {}

# Module-level sprite name tracking for sidecar generation
# Maps: node_name → {component_type → src_name}
_sprite_name_tracker: Dict[str, Dict[str, str]] = {}

# File ID counter
_next_file_id = 100000


def _new_file_id() -> int:
    global _next_file_id
    _next_file_id += 2
    return _next_file_id


def _reset_file_id():
    """Reset for each file conversion to keep IDs deterministic."""
    global _next_file_id
    _next_file_id = 100000


def stable_guid(seed: str) -> str:
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------
def _esc(s: str) -> str:
    """Escape a string for Unity YAML."""
    if not s:
        return ""
    if any(c in s for c in ":{}\n\r\t[]&*?|>!%@`"):
        return s.replace("\\", "\\\\").replace('"', '\\"')
    return s


def _v2(x: float, y: float) -> str:
    return f"{{x: {x}, y: {y}}}"


def _v3(vals: List[float]) -> str:
    if len(vals) >= 3:
        return f"{{x: {vals[0]}, y: {vals[1]}, z: {vals[2]}}}"
    return "{x: 0, y: 0, z: 0}"


def _v4(r: float, g: float, b: float, a: float) -> str:
    return f"{{r: {r:.4f}, g: {g:.4f}, b: {b:.4f}, a: {a:.4f}}}"


def _quat_from_euler(euler: List[float]) -> str:
    """Convert euler angles (degrees) to quaternion YAML string (ZYX order)."""
    ex, ey, ez = [math.radians(v) for v in (euler + [0, 0, 0])[:3]]
    cx, sx = math.cos(ex / 2), math.sin(ex / 2)
    cy, sy = math.cos(ey / 2), math.sin(ey / 2)
    cz, sz = math.cos(ez / 2), math.sin(ez / 2)
    qw = cx * cy * cz + sx * sy * sz
    qx = sx * cy * cz - cx * sy * sz
    qy = cx * sy * cz + sx * cy * sz
    qz = cx * cy * sz - sx * sy * cz
    return f"{{x: {qx:.6f}, y: {qy:.6f}, z: {qz:.6f}, w: {qw:.6f}}}"


# ---------------------------------------------------------------------------
# Color conversion: Cocos (0-255 or 0-1 dict with r,g,b,a) → Unity (0-1)
# ---------------------------------------------------------------------------
def _color_to_unity(color_val: Any) -> Tuple[float, float, float, float]:
    """Normalize a Cocos color to Unity 0-1 range."""
    if color_val is None:
        return (1.0, 1.0, 1.0, 1.0)

    if isinstance(color_val, dict):
        r = color_val.get("r", 255)
        g = color_val.get("g", 255)
        b = color_val.get("b", 255)
        a = color_val.get("a", 255)
    elif isinstance(color_val, (list, tuple)) and len(color_val) >= 3:
        r, g, b = color_val[0], color_val[1], color_val[2]
        a = color_val[3] if len(color_val) > 3 else 255
    else:
        return (1.0, 1.0, 1.0, 1.0)

    # Detect if already in 0-1 range
    if all(0 <= v <= 1.0 for v in (r, g, b, a)) and max(r, g, b, a) <= 1.0:
        return (float(r), float(g), float(b), float(a))
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def _color_yaml(color_val: Any) -> str:
    r, g, b, a = _color_to_unity(color_val)
    return _v4(r, g, b, a)


# ---------------------------------------------------------------------------
# Cocos text alignment → Unity alignment enum
# ---------------------------------------------------------------------------
def _text_anchor(h_align: Any, v_align: Any) -> int:
    """
    Unity TextAnchor: 0=UpperLeft, 1=UpperCenter, 2=UpperRight,
    3=MiddleLeft, 4=MiddleCenter, 5=MiddleRight,
    6=LowerLeft, 7=LowerCenter, 8=LowerRight
    Cocos horizontalAlign: 0=LEFT, 1=CENTER, 2=RIGHT
    Cocos verticalAlign: 0=TOP, 1=CENTER, 2=BOTTOM
    """
    h = int(h_align or 0)
    v = int(v_align or 0)
    # Map Cocos vertical: TOP→Upper(0), CENTER→Middle(1), BOTTOM→Lower(2)
    row = {0: 0, 1: 1, 2: 2}.get(v, 1)
    col = {0: 0, 1: 1, 2: 2}.get(h, 0)
    return row * 3 + col


def _font_style(bold: Any, italic: Any) -> int:
    """Unity FontStyle: 0=Normal, 1=Bold, 2=Italic, 3=BoldAndItalic"""
    b = 1 if bold else 0
    i = 2 if italic else 0
    return b | i


def _overflow_mode(overflow: Any) -> int:
    """
    Cocos overflow: 0=NONE, 1=CLAMP, 2=SHRINK, 3=RESIZE_HEIGHT
    Unity: horizontalOverflow(0=Wrap,1=Overflow), verticalOverflow(0=Truncate,1=Overflow)
    Return (horizontalOverflow, verticalOverflow, bestFit)
    """
    ov = int(overflow or 0)
    if ov == 2:  # SHRINK → bestFit
        return (0, 0, 1)
    if ov == 0:  # NONE → overflow both
        return (1, 1, 0)
    return (0, 0, 0)  # CLAMP / RESIZE_HEIGHT → wrap + truncate


# ---------------------------------------------------------------------------
# Cocos Button transition → Unity transition mode
# ---------------------------------------------------------------------------
def _button_transition(transition: Any) -> int:
    """Cocos: 0=NONE, 1=COLOR, 2=SPRITE, 3=SCALE  Unity: 0=None, 1=ColorTint, 2=SpriteSwap, 3=Animation"""
    t = int(transition or 0)
    return {0: 0, 1: 1, 2: 2, 3: 3}.get(t, 1)


# ---------------------------------------------------------------------------
# Sprite fill type mapping
# ---------------------------------------------------------------------------
def _image_type(cocos_type: Any) -> int:
    """Cocos Sprite.Type: 0=SIMPLE, 1=SLICED, 2=TILED, 3=FILLED
    Unity Image.Type: 0=Simple, 1=Sliced, 2=Tiled, 3=Filled"""
    return int(cocos_type or 0)


def _fill_method(fill_type: Any) -> int:
    """Cocos fillType: 0=HORIZONTAL, 1=VERTICAL, 2=RADIAL
    Unity FillMethod: 0=Horizontal, 1=Vertical, 2=Radial90, 3=Radial180, 4=Radial360"""
    t = int(fill_type or 0)
    return {0: 0, 1: 1, 2: 4}.get(t, 0)


# ---------------------------------------------------------------------------
# Camera clearFlags mapping
# ---------------------------------------------------------------------------
def _camera_clear_flags(flags: Any) -> int:
    """Cocos: 1=SOLID_COLOR, 2=DEPTH_ONLY, 4=DONT_CLEAR
    Unity: 1=Skybox, 2=SolidColor, 3=Depth, 4=Nothing"""
    f = int(flags or 1)
    return {1: 2, 2: 3, 4: 4}.get(f, 2)


# ---------------------------------------------------------------------------
# Build the manifest uuid → Unity guid lookup
# ---------------------------------------------------------------------------
def _build_uuid_guid_map(manifest: Dict[str, Any]) -> Dict[str, str]:
    """Build Cocos uuid → Unity guid mapping from manifest entries."""
    m: Dict[str, str] = {}
    for e in manifest.get("entries", []):
        cuuid = e.get("cocos_uuid", "")
        uguid = e.get("unity_guid", "")
        if cuuid and uguid:
            m[cuuid] = uguid
    return m


def _build_name_to_guid_map(manifest: Dict[str, Any]) -> Dict[str, str]:
    """Build asset filename → Unity guid mapping from manifest entries.

    This enables name-based fallback when UUID resolution fails.
    Multiple naming keys are stored for each entry:
      - full relative src path  (e.g. "images/hero.png")
      - filename with ext       (e.g. "hero.png")
      - filename stem           (e.g. "hero")
    Last-write-wins for duplicate names; full paths take priority.
    """
    name_map: Dict[str, str] = {}
    from pathlib import PurePosixPath
    for e in manifest.get("entries", []):
        uguid = e.get("unity_guid", "")
        src = e.get("src", "")
        if not uguid or not src:
            continue
        normalized = src.replace("\\", "/")
        # Store stem first (lowest priority), then filename, then full path
        stem = PurePosixPath(normalized).stem
        fname = PurePosixPath(normalized).name
        if stem and len(stem) > 2:
            name_map[stem.lower()] = uguid
        if fname:
            name_map[fname.lower()] = uguid
        name_map[normalized.lower()] = uguid
    return name_map


def _resolve_sprite_guid(sprite_ref: Any, uuid_map: Dict[str, str],
                         name_map: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """Try to resolve a Cocos asset reference to a Unity GUID.

    Returns (guid, src_name) tuple.  guid may be "" if not found.
    src_name is the best-effort original file name (from _src_name annotation
    or reverse manifest lookup), may be "" if unknown.

    When name_map is None, falls back to the module-level _global_name_map.

    Resolution order:
      1. Exact UUID match in uuid_map
      2. UUID@subid strip + match
      3. Prefix match (≥8 chars)
      4. Name-based fallback via name_map (NEW)

    Handles:
      - {"__uuid__": "xxx", "_src_name": "hero.png"} — standard resolved format
      - Pure string UUID
      - {"__id__": N, "_unresolved": True, "_src_name": "hero.png"} — failed deep resolution
      - {"_anim_name": "xxx"} — animation clip name reference
      - None / empty
    """
    global _global_name_map
    if name_map is None:
        name_map = _global_name_map
    src_name = ""
    if sprite_ref is None:
        return ("", "")
    if isinstance(sprite_ref, dict):
        src_name = sprite_ref.get("_src_name", "")

        # Warn on unresolved references
        if sprite_ref.get("_unresolved"):
            _id = sprite_ref.get("__id__", "?")
            print(f"  WARNING: Unresolved asset reference {{__id__: {_id}}} — "
                  f"check convert_scene.py deep resolve chain", file=sys.stderr)
            # Even for unresolved refs, try name-based fallback
            if src_name and name_map:
                guid = _resolve_by_name(src_name, name_map)
                if guid:
                    print(f"  → name-based fallback OK: {src_name} → {guid[:16]}...",
                          file=sys.stderr)
                    return (guid, src_name)
            return ("", src_name)

        uuid = sprite_ref.get("__uuid__", "")
        if uuid:
            # Try exact match first
            if uuid in uuid_map:
                return (uuid_map[uuid], src_name)
            # Try UUID@subid format (Cocos uses uuid@subid for sub-assets)
            base_uuid = uuid.split("@")[0] if "@" in uuid else uuid
            if base_uuid != uuid and base_uuid in uuid_map:
                return (uuid_map[base_uuid], src_name)
            # Try partial/prefix match — Cocos 3.x short UUIDs
            # Guard: require minimum 8 chars to avoid false positives
            _MIN_PREFIX_LEN = 8
            if len(base_uuid) >= _MIN_PREFIX_LEN:
                candidates = []
                for k, v in uuid_map.items():
                    if len(k) >= _MIN_PREFIX_LEN and (
                        k.startswith(base_uuid) or base_uuid.startswith(k)
                    ):
                        candidates.append((k, v))
                if len(candidates) == 1:
                    return (candidates[0][1], src_name)
                elif len(candidates) > 1:
                    print(f"  WARNING: UUID prefix {base_uuid[:16]}... matched "
                          f"{len(candidates)} entries — using first",
                          file=sys.stderr)
                    return (candidates[0][1], src_name)

            # UUID not found — try name-based fallback
            if src_name and name_map:
                guid = _resolve_by_name(src_name, name_map)
                if guid:
                    print(f"  → name-based fallback OK: {src_name} → {guid[:16]}...",
                          file=sys.stderr)
                    return (guid, src_name)

            # Not found — warn
            print(f"  WARNING: UUID {uuid[:16]}... not found in manifest "
                  f"({len(uuid_map)} entries)"
                  f"{f', src_name={src_name}' if src_name else ''}",
                  file=sys.stderr)
        # Unresolved or special markers — still try name fallback
        if src_name and name_map:
            guid = _resolve_by_name(src_name, name_map)
            if guid:
                return (guid, src_name)
        return ("", src_name)

    if isinstance(sprite_ref, str):
        if sprite_ref in uuid_map:
            return (uuid_map[sprite_ref], "")
        base = sprite_ref.split("@")[0] if "@" in sprite_ref else sprite_ref
        if base != sprite_ref and base in uuid_map:
            return (uuid_map[base], "")
    return ("", "")


def _resolve_by_name(src_name: str, name_map: Dict[str, str]) -> str:
    """Resolve a source file name to a Unity GUID via the name map.

    Tries: full name → filename → stem (all case-insensitive).
    """
    from pathlib import PurePosixPath
    normalized = src_name.replace("\\", "/").lower()
    # Full path match
    if normalized in name_map:
        return name_map[normalized]
    # Filename match
    fname = PurePosixPath(normalized).name
    if fname and fname in name_map:
        return name_map[fname]
    # Stem match
    stem = PurePosixPath(normalized).stem
    if stem and len(stem) > 2 and stem in name_map:
        return name_map[stem]
    return ""


def _resolve_font_guid(font_ref: Any, uuid_map: Dict[str, str],
                       name_map: Optional[Dict[str, str]] = None) -> str:
    """Resolve a Cocos font reference to a Unity GUID."""
    guid, _ = _resolve_sprite_guid(font_ref, uuid_map, name_map)
    return guid


def _resolve_material_ref(material_ref: Any, uuid_map: Dict[str, str],
                          default: str = "",
                          name_map: Optional[Dict[str, str]] = None) -> str:
    """Resolve a Cocos material reference to a Unity material YAML ref string.

    If a custom material is found via the manifest, returns a custom ref.
    Otherwise returns the provided default (a Unity built-in material ref).
    """
    guid, _ = _resolve_sprite_guid(material_ref, uuid_map, name_map)
    if guid:
        return f"{{fileID: 2100000, guid: {guid}, type: 2}}"
    return default


def _resolve_anim_clips(clips_ref: Any, uuid_map: Dict[str, str],
                        name_map: Optional[Dict[str, str]] = None) -> List[str]:
    """Resolve a list of animation clip references to Unity GUIDs."""
    if not isinstance(clips_ref, list):
        return []
    guids = []
    for clip in clips_ref:
        guid, _ = _resolve_sprite_guid(clip, uuid_map, name_map)
        if guid:
            guids.append(guid)
    return guids


# =====================================================================
# COMPONENT YAML GENERATORS
# Each returns (class_id: int, yaml_body: str)
# class_id 114 = MonoBehaviour (script components), others = native
# =====================================================================

def _yaml_image(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    r, g, b, a = _color_to_unity(f.get("color"))
    sprite_ref = f.get("spriteFrame")
    sprite_guid, sprite_src_name = _resolve_sprite_guid(sprite_ref, uuid_map)
    
    # If no sprite is assigned, set alpha to 0 to make it invisible (User request)
    # We only do this if sprite_ref is explicitly empty, not just unresolved
    if sprite_ref is None:
        a = 0.0
    
    color = _v4(r, g, b, a)

    img_type = _image_type(f.get("type", 0))

    fill_method = _fill_method(f.get("fillType", 0))
    # Cocos fillStart (0-1) → Unity m_FillOrigin (integer: depends on fill method)
    # Horizontal: 0=Left, 1=Right; Vertical: 0=Bottom, 1=Top; Radial: 0-3 (Bottom/Right/Top/Left)
    fill_start = float(f.get("fillStart", 0) or 0)
    fill_origin = int(round(fill_start * 3)) if fill_method >= 2 else (1 if fill_start >= 0.5 else 0)
    fill_amount = float(f.get("fillRange", 1.0) or 1.0)
    # Cocos fillCenter: whether to fill the center portion (for Sliced type)
    fill_center = 1 if f.get("fillCenter", True) else 0
    preserve_aspect = 1 if int(f.get("sizeMode", 0) or 0) == 1 else 0  # CUSTOM=0, TRIMMED=1, RAW=2

    # Material: use custom if provided, otherwise Unity's default UI material
    material_ref = _resolve_material_ref(f.get("material"), uuid_map, UNITY_DEFAULT_UI_MATERIAL)

    sprite_ref_line = f"  m_Sprite: {{fileID: 21300000, guid: {sprite_guid}, type: 3}}" if sprite_guid else "  m_Sprite: {fileID: 0}"
    script_fid, script_guid_val = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.Image", ("11500000", ""))

    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid_val}, type: 3}}",
        f"  m_Color: {color}",
        sprite_ref_line,
        f"  m_Material: {material_ref}",
        f"  m_RaycastTarget: 1",
        f"  m_RaycastPadding: {{x: 0, y: 0, z: 0, w: 0}}",
        f"  m_Maskable: 1",
        f"  m_Type: {img_type}",
        f"  m_PreserveAspect: {preserve_aspect}",
        f"  m_FillCenter: {fill_center}",
        f"  m_FillMethod: {fill_method}",
        f"  m_FillAmount: {fill_amount}",
        f"  m_FillClockwise: 1",
        f"  m_FillOrigin: {fill_origin}",
        f"  m_UseSpriteMesh: 0",
        f"  m_PixelsPerUnitMultiplier: 1",
    ]
    # Emit source name comment for Unity-side name-based binding
    if sprite_src_name:
        lines.append(f"  # cocos_src: {sprite_src_name}")
    return 114, "\n".join(lines) + "\n"


def _yaml_text(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    text = _esc(str(f.get("string", "")) or "")
    
    # Cocos default fontSize is 40. If missing, use 40.
    font_size = int(f.get("fontSize") or 40)
    
    color = _color_yaml(f.get("color"))
    anchor = _text_anchor(f.get("horizontalAlign", 0), f.get("verticalAlign", 1))
    style = _font_style(f.get("enableBold"), f.get("enableItalic"))
    
    # lineHeight in Cocos is absolute pixels, in Unity it's a multiplier.
    line_height = float(f.get("lineHeight") or font_size)
    if line_height > 0 and font_size > 0:
        line_spacing = line_height / font_size
    else:
        line_spacing = 1.0

    h_ov, v_ov, best_fit = _overflow_mode(f.get("overflow", 0))

    # Material: use custom if provided, otherwise Unity's default UI material
    material_ref = _resolve_material_ref(f.get("material"), uuid_map, UNITY_DEFAULT_UI_MATERIAL)

    # Resolve font reference — fallback to Unity built-in Arial
    font_guid = _resolve_font_guid(f.get("font"), uuid_map)
    if font_guid:
        font_ref = f"    m_Font: {{fileID: 11400000, guid: {font_guid}, type: 2}}"
    else:
        font_ref = f"    m_Font: {UNITY_DEFAULT_FONT}"

    # Rich text: enable by default (Cocos RichText / Label with rich text tags)
    rich_text = 1

    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.Text", ("11500000", ""))

    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_Material: {material_ref}",
        f"  m_Color: {color}",
        f"  m_RaycastTarget: 1",
        f"  m_RaycastPadding: {{x: 0, y: 0, z: 0, w: 0}}",
        f"  m_Maskable: 1",
        f"  m_FontData:",
        font_ref,
        f"    m_FontSize: {font_size}",
        f"    m_FontStyle: {style}",
        f"    m_BestFit: {best_fit}",
        f"    m_MinSize: 1",
        f"    m_MaxSize: 300",
        f"    m_Alignment: {anchor}",
        f"    m_AlignByGeometry: 0",
        f"    m_RichText: {rich_text}",
        f"    m_HorizontalOverflow: {h_ov}",
        f"    m_VerticalOverflow: {v_ov}",
        f"    m_LineSpacing: {line_spacing:.2f}",
        f'  m_Text: "{text}"',
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_button(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    interactable = 1 if f.get("interactable", True) else 0
    transition = _button_transition(f.get("transition", 1))
    duration = float(f.get("duration", 0.1) or 0.1)

    normal_color = _color_yaml(f.get("normalColor", {"r": 255, "g": 255, "b": 255, "a": 255}))
    pressed_color = _color_yaml(f.get("pressedColor", {"r": 200, "g": 200, "b": 200, "a": 255}))
    highlight_color = _color_yaml(f.get("hoverColor", {"r": 245, "g": 245, "b": 245, "a": 255}))
    disabled_color = _color_yaml(f.get("disabledColor", {"r": 200, "g": 200, "b": 200, "a": 128}))

    # Sprite transition: resolve normal/pressed/disabled sprites
    normal_sprite_guid, _ = _resolve_sprite_guid(f.get("normalSprite"), uuid_map)
    pressed_sprite_guid, _ = _resolve_sprite_guid(f.get("pressedSprite"), uuid_map)

    highlight_sprite = f"{{fileID: 21300000, guid: {normal_sprite_guid}, type: 3}}" if normal_sprite_guid else "{fileID: 0}"
    pressed_sprite = f"{{fileID: 21300000, guid: {pressed_sprite_guid}, type: 3}}" if pressed_sprite_guid else "{fileID: 0}"
    disabled_sprite = "{fileID: 0}"

    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.Button", ("11500000", ""))

    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_Interactable: {interactable}",
        f"  m_TargetGraphic: {{fileID: 0}}",
        f"  m_Transition: {transition}",
        f"  m_Colors:",
        f"    m_NormalColor: {normal_color}",
        f"    m_HighlightedColor: {highlight_color}",
        f"    m_PressedColor: {pressed_color}",
        f"    m_SelectedColor: {highlight_color}",
        f"    m_DisabledColor: {disabled_color}",
        f"    m_ColorMultiplier: 1",
        f"    m_FadeDuration: {duration}",
        f"  m_SpriteState:",
        f"    m_HighlightedSprite: {highlight_sprite}",
        f"    m_PressedSprite: {pressed_sprite}",
        f"    m_SelectedSprite: {highlight_sprite}",
        f"    m_DisabledSprite: {disabled_sprite}",
        f"  m_Navigation:",
        f"    m_Mode: 3",
        f"    m_WrapAround: 0",
        f"  m_OnClick:",
        f"    m_PersistentCalls:",
        f"      m_Calls: []",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_toggle(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    is_on = 1 if f.get("isChecked", False) else 0
    interactable = 1 if f.get("interactable", True) else 0
    transition = _button_transition(f.get("transition", 1))

    # Resolve checkmark sprite GUID
    check_guid, _ = _resolve_sprite_guid(f.get("checkMark"), uuid_map)
    check_ref = f"{{fileID: 21300000, guid: {check_guid}, type: 3}}" if check_guid else "{fileID: 0}"

    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.Toggle", ("11500000", ""))

    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_Interactable: {interactable}",
        f"  m_TargetGraphic: {{fileID: 0}}",
        f"  m_Transition: {transition}",
        f"  m_IsOn: {is_on}",
        f"  m_Group: {{fileID: 0}}",
        f"  m_Graphic: {{fileID: 0}}",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_toggle_group(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    allow_off = 1 if f.get("allowSwitchOff", False) else 0
    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.ToggleGroup", ("11500000", ""))
    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_AllowSwitchOff: {allow_off}",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_slider(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    value = float(f.get("progress", 0) or 0)
    # Cocos direction: 0=HORIZONTAL, 1=VERTICAL
    direction = int(f.get("direction", 0) or 0)
    reverse = bool(f.get("reverse", False))
    # Unity: 0=LeftToRight, 1=RightToLeft, 2=BottomToTop, 3=TopToBottom
    if direction == 0:
        unity_dir = 1 if reverse else 0
    else:
        unity_dir = 3 if reverse else 2
    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.Slider", ("11500000", ""))

    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_Interactable: 1",
        f"  m_TargetGraphic: {{fileID: 0}}",
        f"  m_Transition: 1",
        f"  m_FillRect: {{fileID: 0}}",
        f"  m_HandleRect: {{fileID: 0}}",
        f"  m_Direction: {unity_dir}",
        f"  m_MinValue: 0",
        f"  m_MaxValue: 1",
        f"  m_WholeNumbers: 0",
        f"  m_Value: {value}",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_scrollrect(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    horizontal = 1 if f.get("horizontal", True) else 0
    vertical = 1 if f.get("vertical", True) else 0
    # Cocos brake is 0-1 (0=no friction, 1=stop immediately)
    # Unity decelerationRate is inverse: 0.135 default (0=instant stop, 1=no deceleration)
    brake = float(f.get("brake", 0) or 0)
    deceleration = max(0, 1.0 - brake) if brake else 0.135
    # Inertia: enabled unless brake = 1 (instant stop)
    inertia = 0 if brake >= 1.0 else 1
    elasticity = float(f.get("bounceDuration", 0.1) or 0.1)
    # Cocos elastic: whether bounce back is enabled
    # Unity MovementType: 0=Unrestricted, 1=Elastic, 2=Clamped
    elastic = f.get("elastic", True)
    movement_type = 1 if elastic else 2
    cancel_inner = 1 if f.get("cancelInnerEvents", True) else 0

    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.ScrollRect", ("11500000", ""))

    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_Content: {{fileID: 0}}",
        f"  m_Horizontal: {horizontal}",
        f"  m_Vertical: {vertical}",
        f"  m_MovementType: {movement_type}",
        f"  m_Elasticity: {elasticity}",
        f"  m_Inertia: {inertia}",
        f"  m_DecelerationRate: {deceleration:.3f}",
        f"  m_ScrollSensitivity: 1",
        f"  m_Viewport: {{fileID: 0}}",
        f"  m_HorizontalScrollbar: {{fileID: 0}}",
        f"  m_VerticalScrollbar: {{fileID: 0}}",
        f"  m_HorizontalScrollbarVisibility: 0",
        f"  m_VerticalScrollbarVisibility: 0",
        f"  m_HorizontalScrollbarSpacing: 0",
        f"  m_VerticalScrollbarSpacing: 0",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_inputfield(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    text = _esc(str(f.get("string", "")) or "")
    placeholder_text = _esc(str(f.get("placeholder", "")) or "")
    char_limit = int(f.get("maxLength", 0) or 0)
    # Cocos inputMode: 0=ANY, 1=EMAIL, 2=NUMERIC, 3=PHONE, 4=URL, 5=DECIMAL, 6=SINGLE_LINE
    # Unity contentType: 0=Standard, 1=Autocorrected, 2=IntegerNumber, 3=DecimalNumber, 4=Alphanumeric, 5=Name, 6=EmailAddress, 7=Password, 8=Pin, 9=Custom
    input_mode = int(f.get("inputMode", 0) or 0)
    content_type = {0: 0, 1: 6, 2: 2, 3: 2, 4: 0, 5: 3, 6: 0}.get(input_mode, 0)
    # Cocos inputFlag: 0=DEFAULT, 1=SENSITIVE, 2=INITIAL_CAPS_WORD, etc
    input_flag = int(f.get("inputFlag", 0) or 0)
    if input_flag == 1:
        content_type = 7  # Password
    # Cocos returnType: 0=DEFAULT, 1=DONE, 2=SEND, 3=SEARCH, 4=GO, 5=NEXT
    # Unity lineType: 0=SingleLine, 1=MultiLineSubmit, 2=MultiLineNewline
    return_type = int(f.get("returnType", 0) or 0)
    line_type = 0 if input_mode == 6 else (0 if return_type == 0 else 0)  # default single-line

    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.InputField", ("11500000", ""))

    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_Interactable: 1",
        f"  m_TargetGraphic: {{fileID: 0}}",
        f"  m_Transition: 1",
        f"  m_TextComponent: {{fileID: 0}}",
        f"  m_Placeholder: {{fileID: 0}}",
        f'  m_Text: "{text}"',
        f"  m_CharacterLimit: {char_limit}",
        f"  m_ContentType: {content_type}",
        f"  m_LineType: {line_type}",
        f"  m_InputType: 0",
        f"  m_KeyboardType: 0",
        f"  m_CharacterValidation: 0",
        f"  m_CaretBlinkRate: 0.85",
        f"  m_CaretWidth: 1",
        f"  m_CaretColor: {_v4(0.1961, 0.1961, 0.1961, 1.0)}",
        f"  m_SelectionColor: {_v4(0.6588, 0.8078, 1.0, 0.7529)}",
        f"  m_ReadOnly: 0",
        f"  m_ShouldActivateOnSelect: 1",
    ]
    if placeholder_text:
        lines.append(f"  # Cocos placeholder text: \"{placeholder_text}\"")
    return 114, "\n".join(lines) + "\n"


def _yaml_rectmask2d(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("UnityEngine.UI.RectMask2D", ("11500000", ""))
    lines = [
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_Padding: {{x: 0, y: 0, z: 0, w: 0}}",
        f"  m_Softness: {{x: 0, y: 0}}",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_outline(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    # Temporarily disabled as per user request.
    return 114, ""






def _yaml_sprite_mask(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    """Generate SpriteMask component from cc.Mask.

    Cocos Mask types: 0=RECT, 1=ELLIPSE, 2=IMAGE_STENCIL
    Unity SpriteMask uses a sprite asset for the mask shape.
    """
    f = comp.get("fields", {})
    # mask_type = int(f.get("type", 0) or 0)
    # inverted = 1 if f.get("inverted") else 0
    alpha_threshold = float(f.get("alphaThreshold", 0.1) or 0.1)

    # Sprite reference (for IMAGE_STENCIL type)
    sprite_ref = "{fileID: 0}"
    sprite_frame = f.get("spriteFrame")
    if sprite_frame and isinstance(sprite_frame, dict):
        uuid = sprite_frame.get("__uuid__", "")
        if uuid and uuid in uuid_map:
            sprite_ref = f"{{fileID: 21300000, guid: {uuid_map[uuid]}, type: 3}}"

    lines = [
        f"  m_CastShadows: 1",
        f"  m_ReceiveShadows: 1",
        f"  m_DynamicOccludee: 1",
        f"  m_StaticShadowCaster: 0",
        f"  m_MotionVectors: 1",
        f"  m_LightProbeUsage: 1",
        f"  m_ReflectionProbeUsage: 1",
        f"  m_RayTracingMode: 0",
        f"  m_RayTraceProcedural: 0",
        f"  m_RenderingLayerMask: 1",
        f"  m_RendererPriority: 0",
        f"  m_Materials:",
        f"  - {{fileID: 10758, guid: 0000000000000000f000000000000000, type: 0}}",
        f"  m_StaticBatchInfo:",
        f"    firstSubMesh: 0",
        f"    subMeshCount: 0",
        f"  m_StaticBatchRoot: {{fileID: 0}}",
        f"  m_ProbeAnchor: {{fileID: 0}}",
        f"  m_LightProbeVolumeOverride: {{fileID: 0}}",
        f"  m_ScaleInLightmap: 1",
        f"  m_ReceiveGI: 1",
        f"  m_PreserveUVs: 0",
        f"  m_IgnoreNormalsForChartDetection: 0",
        f"  m_ImportantGI: 0",
        f"  m_StitchLightmapSeams: 1",
        f"  m_SelectedEditorRenderState: 3",
        f"  m_MinimumChartSize: 4",
        f"  m_AutoUVMaxDistance: 0.5",
        f"  m_AutoUVMaxAngle: 89",
        f"  m_LightmapParameters: {{fileID: 0}}",
        f"  m_SortingLayerID: 0",
        f"  m_SortingLayer: 0",
        f"  m_SortingOrder: 0",
        f"  m_Sprite: {sprite_ref}",
        f"  m_MaskAlphaCutoff: {alpha_threshold}",
        f"  m_FrontSortingLayerID: 0",
        f"  m_BackSortingLayerID: 0",
        f"  m_FrontSortingLayer: 0",
        f"  m_BackSortingLayer: 0",
        f"  m_FrontSortingOrder: 0",
        f"  m_BackSortingOrder: 0",
        f"  m_IsCustomRangeActive: 0",
        f"  m_SpriteSortPoint: 0",
    ]
    return 331, "\n".join(lines) + "\n"



def _yaml_layout_group(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str], unity_comp: str) -> Tuple[int, str]:
    f = comp.get("fields", {})
    spacing_x = float(f.get("spacingX", 0) or 0)
    spacing_y = float(f.get("spacingY", 0) or 0)
    pad_l = int(f.get("paddingLeft", 0) or 0)
    pad_r = int(f.get("paddingRight", 0) or 0)
    pad_t = int(f.get("paddingTop", 0) or 0)
    pad_b = int(f.get("paddingBottom", 0) or 0)

    # Cocos resizeMode: 0=NONE, 1=CONTAINER, 2=CHILDREN
    resize = int(f.get("resizeMode", 0) or 0)
    # Default to 1 (Force Expand) unless Cocos explicitly set it to 0 (NONE)
    # This matches the common Cocos layout behavior where children often fill space
    child_force_w = 0 if resize == 0 else 1
    child_force_h = 0 if resize == 0 else 1


    # Cocos horizontalDirection: 0=LEFT_TO_RIGHT, 1=RIGHT_TO_LEFT
    # Cocos verticalDirection: 0=BOTTOM_TO_TOP, 1=TOP_TO_BOTTOM  (2.x convention)
    # Unity TextAnchor for ChildAlignment: 0=UpperLeft, 1=UpperCenter, 2=UpperRight,
    #   3=MiddleLeft, 4=MiddleCenter, 5=MiddleRight, 6=LowerLeft, 7=LowerCenter, 8=LowerRight
    h_dir = int(f.get("horizontalDirection", 0) or 0)
    v_dir = int(f.get("verticalDirection", 0) or 0)

    # Default to MiddleCenter (4) as it's the most common expectation for "centered" layouts
    row = 1  # Middle
    col = 1  # Center

    if unity_comp == "VerticalLayoutGroup":
        reverse_arrangement = 1 if v_dir == 0 else 0
    elif unity_comp == "HorizontalLayoutGroup":
        reverse_arrangement = 1 if h_dir == 1 else 0
    else:
        # GridLayoutGroup
        reverse_arrangement = 0

    child_alignment = row * 3 + col


    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get(unity_comp, ("11500000", ""))

    lines = [
        f"  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_EditorClassIdentifier: ",
        f"  m_Padding:",

        f"    m_Left: {pad_l}",
        f"    m_Right: {pad_r}",
        f"    m_Top: {pad_t}",
        f"    m_Bottom: {pad_b}",
        f"  m_ChildAlignment: {child_alignment}",
    ]

    if unity_comp == "GridLayoutGroup":
        lines.extend([
            f"  m_CellSize: {{x: 100, y: 100}}",
            f"  m_Spacing: {{x: {spacing_x}, y: {spacing_y}}}",
            f"  m_StartCorner: 0",
            f"  m_StartAxis: 0",
            f"  m_Constraint: 0",
            f"  m_ConstraintCount: 2",
        ])
    else:
        spacing = spacing_x if unity_comp == "HorizontalLayoutGroup" else spacing_y
        lines.extend([
            f"  m_Spacing: {spacing}",
            f"  m_ChildForceExpandWidth: {child_force_w}",
            f"  m_ChildForceExpandHeight: {child_force_h}",
            f"  m_ChildControlWidth: 0",
            f"  m_ChildControlHeight: 0",
            f"  m_ChildScaleWidth: 0",
            f"  m_ChildScaleHeight: 0",
            f"  m_ReverseArrangement: {reverse_arrangement}",
        ])

    return 114, "\n".join(lines) + "\n"


# --- Native components (non-MonoBehaviour) ---

def _yaml_canvas(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    lines = [
        f"  serializedVersion: 3",
        f"  m_RenderMode: 0",
        f"  m_Camera: {{fileID: 0}}",
        f"  m_PlaneDistance: 100",
        f"  m_PixelPerfect: 0",
        f"  m_ReceivesEvents: 1",
        f"  m_OverrideSorting: 0",
        f"  m_OverridePixelPerfect: 0",
        f"  m_SortingBucketNormalizedSize: 0",
        f"  m_VertexColorAlwaysGammaSpace: 0",
        f"  m_AdditionalShaderChannelsFlag: 25",
        f"  m_UpdateRectTransformForStandalone: 0",
        f"  m_SortingLayerID: 0",
        f"  m_SortingOrder: 0",
        f"  m_TargetDisplay: 0",
    ]
    return 223, "\n".join(lines) + "\n"



def _yaml_canvas_scaler(comp: Dict[str, Any], go_fid: int) -> Tuple[int, str]:
    """Generate CanvasScaler based on cc.Canvas designResolution."""
    f = comp.get("fields", {})
    design_res = f.get("designResolution", {})
    w = int(design_res.get("width", 960) if isinstance(design_res, dict) else 960)
    h = int(design_res.get("height", 640) if isinstance(design_res, dict) else 640)
    fit_w = f.get("fitWidth", False)
    fit_h = f.get("fitHeight", False)
    # Unity match: 0=width, 1=height, 0.5=both
    if fit_w and fit_h:
        match = 0.5
    elif fit_h:
        match = 1
    elif fit_w:
        match = 0
    else:
        # Fallback: auto-match height for portrait, width for landscape
        match = 1.0 if w < h else 0.0


    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("CanvasScaler", ("11500000", ""))
    lines = [
        f"  m_ObjectHideFlags: 0",
        f"  m_CorrespondingSourceObject: {{fileID: 0}}",
        f"  m_PrefabInstance: {{fileID: 0}}",
        f"  m_PrefabAsset: {{fileID: 0}}",
        f"  m_GameObject: {{fileID: {go_fid}}}",
        f"  m_Enabled: 1",
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_UiScaleMode: 1",
        f"  m_ReferencePixelsPerUnit: 100",
        f"  m_ScaleFactor: 1",
        f"  m_ReferenceResolution: {{x: {w}, y: {h}}}",
        f"  m_ScreenMatchMode: 0",
        f"  m_MatchWidthOrHeight: {match}",
        f"  m_PhysicalUnit: 3",
        f"  m_FallbackScreenDPI: 96",
        f"  m_DefaultSpriteDPI: 96",
        f"  m_DynamicPixelsPerUnit: 1",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_graphic_raycaster(go_fid: int) -> Tuple[int, str]:
    script_fid, script_guid = BUILTIN_SCRIPT_GUIDS.get("GraphicRaycaster", ("11500000", ""))
    lines = [
        f"  m_ObjectHideFlags: 0",
        f"  m_CorrespondingSourceObject: {{fileID: 0}}",
        f"  m_PrefabInstance: {{fileID: 0}}",
        f"  m_PrefabAsset: {{fileID: 0}}",
        f"  m_GameObject: {{fileID: {go_fid}}}",
        f"  m_Enabled: 1",
        f"  m_Script: {{fileID: {script_fid}, guid: {script_guid}, type: 3}}",
        f"  m_IgnoreReversedGraphics: 1",
        f"  m_BlockingObjects: 0",
        f"  m_BlockingMask:",
        f"    serializedVersion: 2",
        f"    m_Bits: 4294967295",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_camera(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    clear_flags = _camera_clear_flags(f.get("clearFlags", 1))
    bg = _color_yaml(f.get("backgroundColor", {"r": 49, "g": 77, "b": 121, "a": 255}))
    ortho_size = float(f.get("orthoHeight", 5) or 5)
    depth = float(f.get("depth", -1) or -1)
    projection = int(f.get("projection", 1) or 1)
    orthographic = 1 if projection == 1 else 0  # Cocos: 0=PERSPECTIVE, 1=ORTHO
    fov = float(f.get("fov", 60) or 60)
    near_clip = float(f.get("near", 0.3) or 0.3)
    far_clip = float(f.get("far", 1000) or 1000)

    # Viewport rect
    rect = f.get("rect")
    vp_x, vp_y, vp_w, vp_h = 0, 0, 1, 1
    if isinstance(rect, dict):
        vp_x = float(rect.get("x", 0))
        vp_y = float(rect.get("y", 0))
        vp_w = float(rect.get("width", rect.get("w", 1)))
        vp_h = float(rect.get("height", rect.get("h", 1)))

    lines = [
        f"  serializedVersion: 2",
        f"  m_ClearFlags: {clear_flags}",
        f"  m_BackGroundColor: {bg}",
        f"  m_projectionMatrixMode: 1",
        f"  m_GateFitMode: 2",
        f"  m_FOVAxisMode: 0",
        f"  m_Orthographic: {orthographic}",
        f"  m_OrthographicSize: {ortho_size}",
        f"  m_NearClipPlane: {near_clip}",
        f"  m_FarClipPlane: {far_clip}",
        f"  m_FieldOfView: {fov}",
        f"  m_RenderingPath: -1",
        f"  m_TargetTexture: {{fileID: 0}}",
        f"  m_TargetDisplay: 0",
        f"  m_TargetEye: 3",
        f"  m_HDR: 1",
        f"  m_AllowMSAA: 1",
        f"  m_AllowDynamicResolution: 0",
        f"  m_ForceIntoRT: 0",
        f"  m_OcclusionCulling: 1",
        f"  m_StereoConvergence: 10",
        f"  m_StereoSeparation: 0.022",
        f"  m_Depth: {depth}",
        f"  m_NormalizedViewPortRect:",
        f"    serializedVersion: 2",
        f"    x: {vp_x}",
        f"    y: {vp_y}",
        f"    width: {vp_w}",
        f"    height: {vp_h}",
    ]
    return 20, "\n".join(lines) + "\n"


def _yaml_sprite_renderer(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    r, g, b, a = _color_to_unity(f.get("color"))
    sprite_ref = f.get("sprite")
    sprite_guid, sprite_src_name = _resolve_sprite_guid(sprite_ref, uuid_map)
    
    # If no sprite is assigned, set alpha to 0 to make it invisible (User request)
    # We only do this if sprite_ref is explicitly empty, not just unresolved
    if sprite_ref is None:
        a = 0.0

    color = _v4(r, g, b, a)

    sprite_ref_line = f"  m_Sprite: {{fileID: 21300000, guid: {sprite_guid}, type: 3}}" if sprite_guid else "  m_Sprite: {fileID: 0}"

    flip_x = 1 if f.get("flipX", False) else 0
    flip_y = 1 if f.get("flipY", False) else 0

    # Material: use custom if provided, otherwise Unity's Sprites-Default
    material_ref = _resolve_material_ref(f.get("material"), uuid_map, UNITY_SPRITES_DEFAULT_MATERIAL)

    lines = [
        f"  serializedVersion: 2",
        f"  m_Size: {{x: 1, y: 1}}",
        f"  m_Color: {color}",
        sprite_ref,
        f"  m_Material: {material_ref}",
        f"  m_FlipX: {flip_x}",
        f"  m_FlipY: {flip_y}",
        f"  m_DrawMode: 0",
        f"  m_MaskInteraction: 0",
        f"  m_SpriteTileMode: 0",
        f"  m_WasSpriteAssigned: 1",
        f"  m_SpriteSortPoint: 0",
        f"  m_SortingLayerID: 0",
        f"  m_SortingLayer: 0",
        f"  m_SortingOrder: 0",
    ]
    return 212, "\n".join(lines) + "\n"


def _yaml_audio_source(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    volume = float(f.get("volume", 1) or 1)
    loop_val = 1 if f.get("loop", False) else 0
    play_on_awake = 1 if f.get("playOnAwake", True) else 0
    pitch = float(f.get("pitch", 1) or 1)
    clip_guid, _ = _resolve_sprite_guid(f.get("clip"), uuid_map)  # reuse resolver
    clip_ref = f"  m_audioClip: {{fileID: 8300000, guid: {clip_guid}, type: 3}}" if clip_guid else "  m_audioClip: {fileID: 0}"

    lines = [
        f"  serializedVersion: 4",
        clip_ref,
        f"  m_PlayOnAwake: {play_on_awake}",
        f"  m_Volume: {volume}",
        f"  m_Pitch: {pitch}",
        f"  m_Loop: {loop_val}",
        f"  m_Mute: 0",
        f"  m_Spatialize: 0",
        f"  m_SpatializePostEffects: 0",
        f"  m_Priority: 128",
        f"  m_DopplerLevel: 1",
        f"  m_MinDistance: 1",
        f"  m_MaxDistance: 500",
        f"  m_Pan2D: 0",
        f"  m_BypassEffects: 0",
        f"  m_BypassListenerEffects: 0",
        f"  m_BypassReverbZones: 0",
        f"  rolloffMode: 0",
    ]
    return 82, "\n".join(lines) + "\n"


def _yaml_animator(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})

    # Resolve animation clip references
    default_clip_guid, _ = _resolve_sprite_guid(f.get("defaultClip"), uuid_map)
    clip_guids = _resolve_anim_clips(f.get("clips"), uuid_map)

    # Collect clip info for comments
    clip_info_lines = []
    if default_clip_guid:
        clip_info_lines.append(f"  # defaultClip GUID: {default_clip_guid}")
    if clip_guids:
        for i, g in enumerate(clip_guids):
            clip_info_lines.append(f"  # clip[{i}] GUID: {g}")
    if not default_clip_guid and not clip_guids:
        clip_info_lines.append("  # NOTE(cocos2unity): No animation clip references resolved")

    # Unity Animator requires an AnimatorController (.controller) asset.
    # We can't generate one inline in the YAML — emit a reference placeholder
    # and clip GUIDs as comments for post-processing.
    clip_info = "\n".join(clip_info_lines) + "\n" if clip_info_lines else ""

    lines = [
        f"  serializedVersion: 5",
        f"  m_Controller: {{fileID: 0}}",
        f"  # TODO(cocos2unity): Create .controller asset and assign here",
        clip_info.rstrip("\n") if clip_info.strip() else "  # No clips found",
        f"  m_Avatar: {{fileID: 0}}",
        f"  m_ApplyRootMotion: 0",
        f"  m_LinearVelocityBlending: 0",
        f"  m_StabilizeFeet: 0",
        f"  m_HasTransformHierarchy: 1",
        f"  m_AllowConstantClipSamplingOptimization: 1",
        f"  m_KeepAnimatorStateOnDisable: 0",
        f"  m_WriteDefaultValuesOnDisable: 0",
    ]
    return 95, "\n".join(lines) + "\n"


def _yaml_rigidbody2d(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    # Cocos bodyType: 0=STATIC, 1=KINEMATIC, 2=DYNAMIC  Unity: 0=Dynamic, 1=Kinematic, 2=Static
    body_type = int(f.get("bodyType", 2) or 2)
    unity_body = {0: 2, 1: 1, 2: 0}.get(body_type, 0)
    gravity_scale = float(f.get("gravityScale", 1) or 1)
    linear_drag = float(f.get("linearDamping", 0) or 0)
    angular_drag = float(f.get("angularDamping", 0.05) or 0.05)
    # Cocos fixedRotation → Unity m_Constraints: 0=None, 4=FreezeRotation
    fixed_rotation = f.get("fixedRotation", False)
    constraints = 4 if fixed_rotation else 0
    # Cocos allowSleep → Unity m_SleepingMode: 0=NeverSleep, 1=StartAwake
    allow_sleep = f.get("allowSleep", True)
    sleeping_mode = 1 if allow_sleep else 0

    lines = [
        f"  serializedVersion: 4",
        f"  m_BodyType: {unity_body}",
        f"  m_Simulated: 1",
        f"  m_UseFullKinematicContacts: 0",
        f"  m_UseAutoMass: 0",
        f"  m_Mass: 1",
        f"  m_LinearDrag: {linear_drag}",
        f"  m_AngularDrag: {angular_drag}",
        f"  m_GravityScale: {gravity_scale}",
        f"  m_Material: {{fileID: 0}}",
        f"  m_Interpolate: 0",
        f"  m_SleepingMode: {sleeping_mode}",
        f"  m_CollisionDetection: 0",
        f"  m_Constraints: {constraints}",
    ]
    return 50, "\n".join(lines) + "\n"


def _yaml_box_collider2d(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    is_trigger = 1 if f.get("isTrigger", False) else 0
    size = f.get("size", {})
    offset = f.get("offset", {})
    sx = float(size.get("width", size.get("x", 1)) if isinstance(size, dict) else 1)
    sy = float(size.get("height", size.get("y", 1)) if isinstance(size, dict) else 1)
    ox = float(offset.get("x", 0) if isinstance(offset, dict) else 0)
    oy = float(offset.get("y", 0) if isinstance(offset, dict) else 0)

    lines = [
        f"  serializedVersion: 2",
        f"  m_Density: 1",
        f"  m_Material: {{fileID: 0}}",
        f"  m_IsTrigger: {is_trigger}",
        f"  m_UsedByEffector: 0",
        f"  m_UsedByComposite: 0",
        f"  m_Offset: {{x: {ox}, y: {oy}}}",
        f"  m_SpriteTilingProperty:",
        f"    border: {{x: 0, y: 0, z: 0, w: 0}}",
        f"    pivot: {{x: 0.5, y: 0.5}}",
        f"    oldSize: {{x: 1, y: 1}}",
        f"    newSize: {{x: 1, y: 1}}",
        f"    adaptiveTilingThreshold: 0.5",
        f"  m_AutoTiling: 0",
        f"  m_Size: {{x: {sx}, y: {sy}}}",
        f"  m_EdgeRadius: 0",
    ]
    return 61, "\n".join(lines) + "\n"


def _yaml_circle_collider2d(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    is_trigger = 1 if f.get("isTrigger", False) else 0
    radius = float(f.get("radius", 0.5) or 0.5)
    offset = f.get("offset", {})
    ox = float(offset.get("x", 0) if isinstance(offset, dict) else 0)
    oy = float(offset.get("y", 0) if isinstance(offset, dict) else 0)

    lines = [
        f"  serializedVersion: 2",
        f"  m_Density: 1",
        f"  m_Material: {{fileID: 0}}",
        f"  m_IsTrigger: {is_trigger}",
        f"  m_UsedByEffector: 0",
        f"  m_UsedByComposite: 0",
        f"  m_Offset: {{x: {ox}, y: {oy}}}",
        f"  m_Radius: {radius}",
    ]
    return 58, "\n".join(lines) + "\n"


def _yaml_polygon_collider2d(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    is_trigger = 1 if f.get("isTrigger", False) else 0
    points = f.get("points", [])
    # Unity stores as m_Points / m_Paths
    lines = [
        f"  serializedVersion: 2",
        f"  m_Density: 1",
        f"  m_Material: {{fileID: 0}}",
        f"  m_IsTrigger: {is_trigger}",
        f"  m_UsedByEffector: 0",
        f"  m_UsedByComposite: 0",
        f"  m_Offset: {{x: 0, y: 0}}",
        f"  m_SpriteTilingProperty:",
        f"    border: {{x: 0, y: 0, z: 0, w: 0}}",
        f"    pivot: {{x: 0.5, y: 0.5}}",
        f"    oldSize: {{x: 1, y: 1}}",
        f"    newSize: {{x: 1, y: 1}}",
        f"    adaptiveTilingThreshold: 0.5",
        f"  m_AutoTiling: 0",
        f"  m_UseDelaunayMesh: 0",
    ]
    if isinstance(points, list) and points:
        lines.append(f"  m_Points:")
        lines.append(f"  - m_Paths:")
        path_lines = []
        for pt in points:
            if isinstance(pt, dict):
                path_lines.append(f"    - {{x: {pt.get('x', 0)}, y: {pt.get('y', 0)}}}")
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                path_lines.append(f"    - {{x: {pt[0]}, y: {pt[1]}}}")
        lines.extend(path_lines)
    return 60, "\n".join(lines) + "\n"


def _yaml_particle_system(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    # Particle system is extremely complex; emit a skeleton with a note
    lines = [
        f"  serializedVersion: 8",
        f"  # NOTE(cocos2unity): ParticleSystem requires manual configuration",
        f"  # Cocos ParticleSystem2D uses a different data model than Unity's Shuriken",
        f"  m_LengthInSec: 5",
        f"  m_Looping: 1",
        f"  m_Prewarm: 0",
        f"  m_PlayOnAwake: 1",
        f"  m_UseUnscaledTime: 0",
        f"  m_AutoRandomSeed: 1",
        f"  m_MaxParticles: 1000",
    ]
    return 198, "\n".join(lines) + "\n"


def _yaml_spine(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    default_skin = f.get("defaultSkin", "default") or "default"
    default_anim = f.get("defaultAnimation", "") or ""
    loop = 1 if f.get("loop", True) else 0
    premultiplied = 1 if f.get("premultipliedAlpha", True) else 0

    # Resolve skeletonData asset GUID
    skel_guid, _ = _resolve_sprite_guid(f.get("skeletonData"), uuid_map)

    # Spine.Unity.SkeletonAnimation uses SkeletonDataAsset reference
    if skel_guid:
        skel_ref = f"  skeletonDataAsset: {{fileID: 11400000, guid: {skel_guid}, type: 2}}"
    else:
        skel_ref = "  skeletonDataAsset: {fileID: 0}"
        skel_ref += "\n  # TODO(cocos2unity): Assign SkeletonDataAsset in Inspector"

    lines = [
        f"  # Spine.Unity.SkeletonAnimation — requires Spine-Unity runtime package",
        f"  m_Script: {{fileID: 0}}",
        f"  # TODO(cocos2unity): Set m_Script to Spine.Unity.SkeletonAnimation GUID",
        skel_ref,
        f"  initialSkinName: {default_skin}",
        f"  initialAnimation: {default_anim}" if default_anim else "  initialAnimation:",
        f"  initialLoop: {loop}",
        f"  premultipliedAlpha: {premultiplied}",
        f"  timeScale: 1",
        f"  unscaledTime: 0",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_dragonbones(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    f = comp.get("fields", {})
    armature_name = f.get("armatureName", "") or ""
    anim_name = f.get("animationName", "") or ""
    play_times = int(f.get("playTimes", -1) if f.get("playTimes") is not None else -1)
    time_scale = float(f.get("timeScale", 1) or 1)

    # Resolve dragonAsset (skeleton data) GUID
    dragon_guid, _ = _resolve_sprite_guid(f.get("dragonAsset"), uuid_map)

    # Resolve dragonAtlasAsset (atlas data) GUID
    atlas_guid, _ = _resolve_sprite_guid(f.get("dragonAtlasAsset"), uuid_map)

    if dragon_guid:
        dragon_ref = f"  unityDragonBonesData: {{fileID: 11400000, guid: {dragon_guid}, type: 2}}"
    else:
        dragon_ref = "  unityDragonBonesData: {fileID: 0}"
        dragon_ref += "\n  # TODO(cocos2unity): Assign DragonBonesData in Inspector"

    if atlas_guid:
        atlas_ref = f"  unityDragonBonesAtlasAsset: {{fileID: 11400000, guid: {atlas_guid}, type: 2}}"
    else:
        atlas_ref = "  unityDragonBonesAtlasAsset: {fileID: 0}"

    lines = [
        f"  # DragonBones.UnityArmatureComponent — requires DragonBones Unity package",
        f"  m_Script: {{fileID: 0}}",
        f"  # TODO(cocos2unity): Set m_Script to DragonBones.UnityArmatureComponent GUID",
        dragon_ref,
        atlas_ref,
        f"  armatureName: {armature_name}" if armature_name else "  armatureName:",
        f"  animationName: {anim_name}" if anim_name else "  animationName:",
        f"  playTimes: {play_times}",
        f"  timeScale: {time_scale}",
        f"  unscaledTime: 0",
        f"  flipX: 0",
        f"  flipY: 0",
        f"  closeCombineMeshs: 0",
    ]
    return 114, "\n".join(lines) + "\n"


def _yaml_canvas_group(comp: Dict[str, Any], go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    """Generate CanvasGroup from cc.UIOpacity component."""
    f = comp.get("fields", {})
    opacity = f.get("opacity", 255)
    if opacity is None:
        opacity = 255
    alpha = round(float(opacity) / 255.0, 4)
    lines = [
        f"  m_Alpha: {alpha}",
        f"  m_Interactable: 1",
        f"  m_BlocksRaycasts: 1",
        f"  m_IgnoreParentGroups: 0",
    ]
    return 225, "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
_YAML_GENERATORS: Dict[str, Any] = {
    "UnityEngine.UI.Image":       _yaml_image,
    "UnityEngine.UI.Text":        _yaml_text,
    "UnityEngine.UI.Button":      _yaml_button,
    "UnityEngine.UI.Toggle":      _yaml_toggle,
    "UnityEngine.UI.ToggleGroup": _yaml_toggle_group,
    "UnityEngine.UI.Slider":      _yaml_slider,
    "UnityEngine.UI.ScrollRect":  _yaml_scrollrect,
    "UnityEngine.UI.InputField":  _yaml_inputfield,
    "UnityEngine.UI.RectMask2D":  _yaml_rectmask2d,
    "UnityEngine.UI.Outline":     _yaml_outline,
    "SpriteMask":                 _yaml_sprite_mask,

    "Camera":                     _yaml_camera,
    "SpriteRenderer":             _yaml_sprite_renderer,
    "AudioSource":                _yaml_audio_source,
    "Animator":                   _yaml_animator,
    "ParticleSystem":             _yaml_particle_system,
    "Rigidbody2D":                _yaml_rigidbody2d,
    "BoxCollider2D":              _yaml_box_collider2d,
    "CircleCollider2D":           _yaml_circle_collider2d,
    "PolygonCollider2D":          _yaml_polygon_collider2d,
    "Spine.Unity.SkeletonAnimation": _yaml_spine,
    "DragonBones.UnityArmatureComponent": _yaml_dragonbones,
    "CanvasGroup":                _yaml_canvas_group,
    "Canvas":                     _yaml_canvas,
}


def _unity_component_yaml(unity_comp: str, comp: Dict[str, Any],
                          go_fid: int, uuid_map: Dict[str, str]) -> Tuple[int, str]:
    """Return (unity_class_id, extra_yaml_lines) for a mapped component."""
    # Layout groups need the component name passed through
    if unity_comp in ("HorizontalLayoutGroup", "VerticalLayoutGroup", "GridLayoutGroup"):
        return _yaml_layout_group(comp, go_fid, uuid_map, unity_comp)

    gen = _YAML_GENERATORS.get(unity_comp)
    if gen:
        return gen(comp, go_fid, uuid_map)

    # Fallback: native class or unknown MonoBehaviour
    class_id = NATIVE_CLASS_IDS.get(unity_comp, 114)
    fields = comp.get("fields", {})
    extra = ""
    if fields:
        field_comments = []
        for k, v in fields.items():
            val_str = json.dumps(v, ensure_ascii=False)[:80]
            field_comments.append(f"  # TODO(cocos2unity): {k} = {val_str}")
        extra = "\n".join(field_comments) + "\n"
    return class_id, extra


# =====================================================================
# MAIN YAML GENERATION
# =====================================================================

def plan_to_unity_yaml(plan: Dict[str, Any], is_scene: bool = False,
                       manifest: Optional[Dict[str, Any]] = None,
                       ppu: float = 100.0, convert_pos: bool = False) -> str:

    """Convert a plan.json structure into Unity YAML format with full property mapping.

    For prefabs: generates a Prefab YAML that Unity imports as a native prefab.
    For scenes: generates a Scene YAML that Unity imports as a native scene.
    """
    global _global_name_map, _sprite_name_tracker
    nodes = plan.get("nodes", [])
    if not nodes:
        return ""

    uuid_map = _build_uuid_guid_map(manifest) if manifest else {}
    _global_name_map = _build_name_to_guid_map(manifest) if manifest else {}
    _sprite_name_tracker = {}  # Reset per file

    lines: List[str] = [
        "%YAML 1.1",
        "%TAG !u! tag:unity3d.com,2011:",
    ]

    # Build index -> sequential ID mapping
    index_to_fid: Dict[int, int] = {}
    transform_fids: Dict[int, int] = {}

    for node in nodes:
        idx = node["index"]
        go_fid = _new_file_id()
        tr_fid = _new_file_id()
        index_to_fid[idx] = go_fid
        transform_fids[idx] = tr_fid

    # Build parent -> children mapping (sorted by z_order)
    children_by_parent: Dict[int, List[Tuple[int, int]]] = {}
    for node in nodes:
        idx = node["index"]
        parent_idx = node.get("parent_index")
        if parent_idx is not None and parent_idx in index_to_fid:
            z = node.get("z_order", 0) or 0
            children_by_parent.setdefault(parent_idx, []).append((z, idx))
    for k in children_by_parent:
        children_by_parent[k].sort(key=lambda x: x[0])

    # --- Pre-pass: identify Canvas nodes and build ancestry for UI propagation ---
    # In Unity, ALL descendants of a Canvas node must use RectTransform (layer 5).
    # We also track which nodes are Canvas so we can detect nested Canvas.
    node_by_idx: Dict[int, Dict[str, Any]] = {n["index"]: n for n in nodes}
    canvas_node_indices: set = set()
    for node in nodes:
        if any(c.get("unity_component") == "Canvas" for c in node.get("components", [])):
            canvas_node_indices.add(node["index"])

    def _is_under_canvas(node_idx: int) -> bool:
        """Check if this node is a descendant of any Canvas node."""
        visited = set()
        cur = node_idx
        while cur is not None and cur not in visited:
            visited.add(cur)
            n = node_by_idx.get(cur)
            if n is None:
                break
            parent = n.get("parent_index")
            if parent is not None and parent in canvas_node_indices:
                return True
            cur = parent
        return False

    def _is_nested_canvas(node_idx: int) -> bool:
        """Check if this Canvas node is nested under another Canvas."""
        return node_idx in canvas_node_indices and _is_under_canvas(node_idx)

    # Emit each GameObject + Transform + Components
    for node in nodes:
        idx = node["index"]
        go_fid = index_to_fid[idx]
        tr_fid = transform_fids[idx]
        name = _esc(node.get("name", f"Node_{idx}"))
        active = 1 if node.get("active", True) else 0

        t = node.get("transform", {})
        pos = t.get("position", [0, 0, 0])
        euler = t.get("euler", [0, 0, 0])
        scale = t.get("scale", [1, 1, 1])

        # Detect UI vs non-UI — self has UI components OR is under a Canvas
        has_own_ui = any(
            (c.get("unity_component") or "").startswith("UnityEngine.UI.")
            or c.get("unity_component") == "RectTransform"
            or c.get("unity_component") == "RectTransform.anchors"
            or c.get("unity_component") == "Canvas"
            for c in node.get("components", [])
        )
        # Inherit UI status from Canvas ancestor
        has_ui = has_own_ui or _is_under_canvas(idx)
        has_canvas = idx in canvas_node_indices
        is_nested = _is_nested_canvas(idx)

        # Layer: 5 = UI for nodes with UI components or under Canvas, 0 = Default
        layer = 5 if has_ui else 0

        # Collect component fileIDs and YAML for this GO
        comp_fids: List[int] = [tr_fid]
        comp_yamls: List[str] = []

        # Track Canvas fields for CanvasScaler injection
        canvas_comp_data: Optional[Dict[str, Any]] = None

        # Node-level color: inject into component fields if the component
        # supports color (Image, Text, SpriteRenderer, etc.)
        node_color = node.get("color")

        for comp in node.get("components", []):
            unity_comp = comp.get("unity_component")
            # Skip RectTransform (handled separately) and temporarily disabled components (Outline)
            if not unity_comp or unity_comp in ("RectTransform", "RectTransform.anchors", "UnityEngine.UI.Outline"):
                continue

            if comp.get("note", "").startswith("Custom"):
                # Custom script: emit a MonoBehaviour with script reference if found
                c_fid = _new_file_id()
                comp_fids.append(c_fid)
                custom_name = comp.get("unity_component") or comp.get("cocos_type", "CustomScript").split(".")[-1]
                
                # Try to resolve GUID for this custom script
                script_guid = _script_guid_map.get(custom_name, "")
                if script_guid:
                    script_ref = f"{{fileID: 11500000, guid: {script_guid}, type: 3}}"
                    todo_comment = ""
                else:
                    script_ref = "{fileID: 0}"
                    todo_comment = f"  # TODO(cocos2unity): Assign {custom_name}.cs script reference\n"

                comp_yamls.append(
                    f"--- !u!114 &{c_fid}\n"
                    f"MonoBehaviour:\n"
                    f"  m_ObjectHideFlags: 0\n"
                    f"  m_CorrespondingSourceObject: {{fileID: 0}}\n"
                    f"  m_PrefabInstance: {{fileID: 0}}\n"
                    f"  m_PrefabAsset: {{fileID: 0}}\n"
                    f"  m_GameObject: {{fileID: {go_fid}}}\n"
                    f"  m_Enabled: 1\n"
                    f"  m_EditorHideFlags: 0\n"
                    f"  m_Script: {script_ref}\n"
                    f"{todo_comment}"
                    f"  m_EditorClassIdentifier: \n"
                )

                continue

            if unity_comp is None:
                continue

            if unity_comp == "Canvas":
                canvas_comp_data = comp

            # Inject node-level color into component fields if present.
            # Since we now have hierarchy color inheritance in plan.json, 
            # node["color"] is the final effective color.
            if node_color and unity_comp in ("UnityEngine.UI.Image", "UnityEngine.UI.Text", "SpriteRenderer"):
                comp_fields = comp.get("fields", {})
                comp_color = comp_fields.get("color")
                # For UI/Sprites, if no specific component color is set, use the inherited node color.
                if not comp_color or (comp_color.get("r", 255) == 255 and comp_color.get("g", 255) == 255 and comp_color.get("b", 255) == 255 and comp_color.get("a", 255) == 255):
                    comp_fields = dict(comp_fields)
                    comp_fields["color"] = node_color
                    comp = dict(comp)
                    comp["fields"] = comp_fields


            c_fid = _new_file_id()
            comp_fids.append(c_fid)

            class_id, comp_yaml_extra = _unity_component_yaml(unity_comp, comp, go_fid, uuid_map)

            # For MonoBehaviour components (class_id 114), use the short name
            # For native components (Camera, SpriteRenderer, etc.), use full name
            if class_id == 114:
                comp_type_name = "MonoBehaviour"
            else:
                comp_type_name = unity_comp.split(".")[-1]

            comp_yamls.append(
                f"--- !u!{class_id} &{c_fid}\n"
                f"{comp_type_name}:\n"
                f"  m_ObjectHideFlags: 0\n"
                f"  m_CorrespondingSourceObject: {{fileID: 0}}\n"
                f"  m_PrefabInstance: {{fileID: 0}}\n"
                f"  m_PrefabAsset: {{fileID: 0}}\n"
                f"  m_GameObject: {{fileID: {go_fid}}}\n"
                f"  m_Enabled: 1\n"
                f"{comp_yaml_extra}"
            )

        # Auto-inject CanvasScaler + GraphicRaycaster for ROOT Canvas nodes only.
        # Nested Canvas (Canvas under another Canvas) should NOT have these companions.
        if has_canvas and canvas_comp_data is not None and not is_nested:
            # CanvasScaler
            cs_fid = _new_file_id()
            comp_fids.append(cs_fid)
            cs_class_id, cs_yaml = _yaml_canvas_scaler(canvas_comp_data, go_fid)
            comp_yamls.append(
                f"--- !u!{cs_class_id} &{cs_fid}\n"
                f"MonoBehaviour:\n"
                f"{cs_yaml}"
            )
            # GraphicRaycaster
            gr_fid = _new_file_id()
            comp_fids.append(gr_fid)
            gr_class_id, gr_yaml = _yaml_graphic_raycaster(go_fid)
            comp_yamls.append(
                f"--- !u!{gr_class_id} &{gr_fid}\n"
                f"MonoBehaviour:\n"
                f"{gr_yaml}"
            )

        # Auto-inject CanvasGroup for node-level opacity (< 255)
        node_opacity = node.get("opacity")
        if node_opacity is not None and node_opacity < 255 and has_ui:
            cg_fid = _new_file_id()
            comp_fids.append(cg_fid)
            alpha = round(node_opacity / 255.0, 4)
            cg_yaml = (
                f"--- !u!225 &{cg_fid}\n"
                f"CanvasGroup:\n"
                f"  m_ObjectHideFlags: 0\n"
                f"  m_GameObject: {{fileID: {go_fid}}}\n"
                f"  m_Enabled: 1\n"
                f"  m_Alpha: {alpha}\n"
                f"  m_Interactable: 1\n"
                f"  m_BlocksRaycasts: 1\n"
                f"  m_IgnoreParentGroups: 0\n"
            )
            comp_yamls.append(cg_yaml)

        # Auto-inject SpriteRenderer color alpha for non-UI nodes with opacity
        if node_opacity is not None and node_opacity < 255 and not has_ui:
            # For non-UI nodes, opacity is handled via color alpha on SpriteRenderer
            # which should already be part of node color; just emit a comment
            pass  # color alpha is baked into the node color field

        # Extract RectTransform data from plan components
        size_w, size_h = 0, 0
        anchor_min = [0.5, 0.5]
        anchor_max = [0.5, 0.5]
        pivot = [0.5, 0.5]
        widget_offsets: Dict[str, Any] = {}
        widget_flags: Dict[str, bool] = {}

        for comp in node.get("components", []):
            if comp.get("unity_component") == "RectTransform":
                ct = comp.get("fields", {}).get("contentSize", {})
                size_w = ct.get("width", 0)
                size_h = ct.get("height", 0)
                # For UI, size stays in pixels. For non-UI, scale if requested.
                if not has_ui and convert_pos:
                    size_w /= ppu
                    size_h /= ppu
                ap = comp.get("fields", {}).get("anchorPoint", {})
                if ap:
                    pivot = [ap.get("x", 0.5), ap.get("y", 0.5)]
                    # Cocos anchorPoint also drives child positioning reference,
                    # which maps to Unity's AnchorMin/Max when no Widget is present.
                    if not any(c.get("unity_component") == "RectTransform.anchors" for c in node.get("components", [])):
                        anchor_min = [ap.get("x", 0.5), ap.get("y", 0.5)]
                        anchor_max = [ap.get("x", 0.5), ap.get("y", 0.5)]
            elif comp.get("unity_component") == "RectTransform.anchors":
                anchors = comp.get("anchors", {})
                anchor_min = anchors.get("anchorMin", [0.5, 0.5])
                anchor_max = anchors.get("anchorMax", [0.5, 0.5])
                widget_offsets = anchors.get("offsets", {})
                # For UI, offsets stay in pixels. For non-UI, scale if requested.
                if not has_ui and convert_pos:
                    for k in widget_offsets:
                        if widget_offsets[k] is not None:
                            widget_offsets[k] = float(widget_offsets[k]) / ppu
                widget_flags = anchors.get("flags", {})


        # Compute anchored position / offsetMin / offsetMax from Widget data
        # Cocos position is relative to parent's origin (defined by parent's anchor/pivot).
        # Unity anchoredPosition is relative to child's anchor position in parent's rect.
        # Conversion: unity_anchored = (cocos_pos + parent_size * (parent_pivot - child_anchor))
        anchored_x = pos[0]
        anchored_y = pos[1]
        
        # Apply PPU scaling to position for non-UI if requested
        if not has_ui and convert_pos:
            pos = [p / ppu for p in pos]

        # Root Canvas nodes in Unity should always be at (0,0) world/local pos, 
        # whereas in Cocos they often carry a design-resolution-center offset.
        if has_canvas and not is_nested:
            anchored_x = 0
            anchored_y = 0
            pos = [0, 0, 0] # Force local position to zero as well for root canvas

        # If stretch mode (both sides anchored), use offsetMin/offsetMax instead of anchoredPosition
        stretch_x = anchor_min[0] == 0 and anchor_max[0] == 1
        stretch_y = anchor_min[1] == 0 and anchor_max[1] == 1

        # Adjust anchoredPosition for parent-child anchor/pivot difference (UI nodes only)
        parent_idx_for_anchor = node.get("parent_index")
        if has_ui and parent_idx_for_anchor is not None:
            parent_node = node_by_idx.get(parent_idx_for_anchor)
            if parent_node:
                # Get parent's size and pivot
                parent_size_w, parent_size_h = 0, 0
                parent_pivot = [0.5, 0.5]
                for pcomp in parent_node.get("components", []):
                    if pcomp.get("unity_component") == "RectTransform":
                        pct = pcomp.get("fields", {}).get("contentSize", {})
                        parent_size_w = pct.get("width", 0)
                        parent_size_h = pct.get("height", 0)
                        pap = pcomp.get("fields", {}).get("anchorPoint", {})
                        if pap:
                            parent_pivot = [pap.get("x", 0.5), pap.get("y", 0.5)]
                        break
                
                # Formula: unity_anchored = cocos_pos + parent_size * (parent_pivot - child_anchor)
                anchored_x = pos[0] + parent_size_w * (parent_pivot[0] - anchor_min[0])
                anchored_y = pos[1] + parent_size_h * (parent_pivot[1] - anchor_min[1])

                # Use widget offsets to override anchoredPosition if available (Cocos position can be stale)
                has_widget = any(c.get("unity_component") == "RectTransform.anchors" for c in node.get("components", []))
                if has_widget:
                    left = widget_offsets.get("left")
                    right = widget_offsets.get("right")
                    top = widget_offsets.get("top")
                    bottom = widget_offsets.get("bottom")
                    
                    if not stretch_x:
                        if left is not None and anchor_min[0] == 0:
                            anchored_x = float(left) + (size_w * pivot[0])
                        elif right is not None and anchor_min[0] == 1:
                            anchored_x = -float(right) - (size_w * (1 - pivot[0]))
                    
                    if not stretch_y:
                        if bottom is not None and anchor_min[1] == 0:
                            anchored_y = float(bottom) + (size_h * pivot[1])
                        elif top is not None and anchor_min[1] == 1:
                            anchored_y = -float(top) - (size_h * (1 - pivot[1]))

        if has_ui and (stretch_x or stretch_y):

            # In stretch mode, Unity uses offsetMin/offsetMax relative to anchors.
            # sizeDelta is used differently: sizeDelta.x = offsetMax.x - offsetMin.x
            if stretch_x and stretch_y:
                off_min_x = float(widget_offsets.get("left", 0) or 0)
                off_min_y = float(widget_offsets.get("bottom", 0) or 0)
                off_max_x = -float(widget_offsets.get("right", 0) or 0)
                off_max_y = -float(widget_offsets.get("top", 0) or 0)
                size_w = off_max_x - off_min_x
                size_h = off_max_y - off_min_y
                anchored_x = (off_min_x + off_max_x) / 2
                anchored_y = (off_min_y + off_max_y) / 2
            elif stretch_x:
                off_min_x = float(widget_offsets.get("left", 0) or 0)
                off_max_x = -float(widget_offsets.get("right", 0) or 0)
                size_w = off_max_x - off_min_x
                anchored_x = (off_min_x + off_max_x) / 2
            elif stretch_y:
                off_min_y = float(widget_offsets.get("bottom", 0) or 0)
                off_max_y = -float(widget_offsets.get("top", 0) or 0)
                size_h = off_max_y - off_min_y
                anchored_y = (off_min_y + off_max_y) / 2


        transform_class_id = 224 if has_ui else 4

        # Get children transforms
        has_children = idx in children_by_parent and len(children_by_parent[idx]) > 0
        if has_children:
            child_lines = []
            for _, child_idx in children_by_parent[idx]:
                child_tr_fid = transform_fids[child_idx]
                child_lines.append(f"  - {{fileID: {child_tr_fid}}}")
            child_tr_refs = "\n".join(child_lines)
            children_block = f"  m_Children:\n{child_tr_refs}"
        else:
            children_block = "  m_Children: []"

        # Parent transform ref
        parent_idx = node.get("parent_index")
        if parent_idx is not None and parent_idx in transform_fids:
            parent_tr_ref = f"{{fileID: {transform_fids[parent_idx]}}}"
        else:
            parent_tr_ref = "{fileID: 0}"

        # --- GameObject ---
        comp_refs = "\n".join(f"  - component: {{fileID: {fid}}}" for fid in comp_fids)
        lines.append(
            f"--- !u!1 &{go_fid}\n"
            f"GameObject:\n"
            f"  m_ObjectHideFlags: 0\n"
            f"  m_CorrespondingSourceObject: {{fileID: 0}}\n"
            f"  m_PrefabInstance: {{fileID: 0}}\n"
            f"  m_PrefabAsset: {{fileID: 0}}\n"
            f"  serializedVersion: 6\n"
            f"  m_Component:\n"
            f"{comp_refs}\n"
            f"  m_Layer: {layer}\n"
            f'  m_Name: "{name}"\n'
            f"  m_TagString: Untagged\n"
            f"  m_Icon: {{fileID: 0}}\n"
            f"  m_NavMeshLayer: 0\n"
            f"  m_StaticEditorFlags: 0\n"
            f"  m_IsActive: {active}"
        )

        # --- Transform ---
        if has_ui:
            lines.append(
                f"--- !u!{transform_class_id} &{tr_fid}\n"
                f"RectTransform:\n"
                f"  m_ObjectHideFlags: 0\n"
                f"  m_CorrespondingSourceObject: {{fileID: 0}}\n"
                f"  m_PrefabInstance: {{fileID: 0}}\n"
                f"  m_PrefabAsset: {{fileID: 0}}\n"
                f"  m_GameObject: {{fileID: {go_fid}}}\n"
                f"  m_LocalRotation: {_quat_from_euler(euler)}\n"
                f"  m_LocalPosition: {_v3([pos[0], pos[1], pos[2] if len(pos) > 2 else 0])}\n"
                f"  m_LocalScale: {_v3(scale)}\n"
                f"  m_ConstrainProportionsScale: 0\n"
                f"{children_block}\n"
                f"  m_Father: {parent_tr_ref}\n"
                f"  m_LocalEulerAnglesHint: {_v3(euler)}\n"
                f"  m_AnchorMin: {_v2(anchor_min[0], anchor_min[1])}\n"
                f"  m_AnchorMax: {_v2(anchor_max[0], anchor_max[1])}\n"
                f"  m_AnchoredPosition: {_v2(anchored_x, anchored_y)}\n"
                f"  m_SizeDelta: {_v2(size_w, size_h)}\n"
                f"  m_Pivot: {_v2(pivot[0], pivot[1])}"
            )
        else:
            lines.append(
                f"--- !u!{transform_class_id} &{tr_fid}\n"
                f"Transform:\n"
                f"  m_ObjectHideFlags: 0\n"
                f"  m_CorrespondingSourceObject: {{fileID: 0}}\n"
                f"  m_PrefabInstance: {{fileID: 0}}\n"
                f"  m_PrefabAsset: {{fileID: 0}}\n"
                f"  m_GameObject: {{fileID: {go_fid}}}\n"
                f"  serializedVersion: 2\n"
                f"  m_LocalRotation: {_quat_from_euler(euler)}\n"
                f"  m_LocalPosition: {_v3(pos)}\n"
                f"  m_LocalScale: {_v3(scale)}\n"
                f"  m_ConstrainProportionsScale: 0\n"
                f"{children_block}\n"
                f"  m_Father: {parent_tr_ref}\n"
                f"  m_LocalEulerAnglesHint: {_v3(euler)}"
            )

        # --- Additional Components ---
        for cy in comp_yamls:
            lines.append(cy)

    return "\n".join(lines) + "\n"


# =====================================================================
# META GENERATORS
# =====================================================================

def default_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
DefaultImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def prefab_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
PrefabImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def scene_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
DefaultImporter:
  externalObjects: {{}}
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def _collect_sprite_names(plan: Dict[str, Any]) -> Dict[str, str]:
    """Collect a {node_path/component: src_name} map from plan nodes.

    This is written as a sidecar JSON file for Unity Editor scripts to use
    when binding sprites by name.  Format:
      { "NodeName/Image": "hero.png", "BG/Image": "bg_main.png", ... }
    """
    result: Dict[str, str] = {}
    # Also include the uuid_to_src table from plan (generated by convert_scene)
    uuid_to_src = plan.get("uuid_to_src", {})
    if uuid_to_src:
        result["__uuid_to_src__"] = uuid_to_src  # type: ignore

    for node in plan.get("nodes", []):
        node_name = node.get("name", "?")
        for comp in node.get("components", []):
            unity_comp = comp.get("unity_component", "")
            fields = comp.get("fields", {})
            # Check known sprite reference fields
            for field_name in ("spriteFrame", "sprite", "normalSprite",
                               "pressedSprite", "checkMark", "barSprite"):
                ref = fields.get(field_name)
                if isinstance(ref, dict) and ref.get("_src_name"):
                    key = f"{node_name}/{unity_comp or comp.get('cocos_type', '?')}/{field_name}"
                    result[key] = ref["_src_name"]
    return result


# =====================================================================
# SINGLE + BATCH CONVERSION
# =====================================================================

def convert_single(src_file: Path, dst_file: Path, manifest: Dict[str, Any],
                   ppu: float, convert_pos: bool) -> Dict[str, Any]:
    """Convert a single Cocos structural file to Unity native format."""
    _reset_file_id()  # Reset per file for deterministic output

    data = load_cocos(src_file)
    fmt = detect_format(data)

    if fmt == "2.x":
        plan = build_plan_2x(data, manifest, ppu, convert_pos, src_file)
    else:
        plan = build_plan_3x(data, manifest, ppu, convert_pos, src_file)


    ext = src_file.suffix.lower()
    is_scene = ext in (".scene", ".fire")

    yaml_content = plan_to_unity_yaml(plan, is_scene=is_scene, manifest=manifest, ppu=ppu, convert_pos=convert_pos)


    dst_file.parent.mkdir(parents=True, exist_ok=True)
    dst_file.write_text(yaml_content, encoding="utf-8")

    # Generate sprite_name_map.json sidecar for Unity-side name-based binding
    sprite_name_map = _collect_sprite_names(plan)
    name_map_path = dst_file.with_suffix(".sprite_names.json")
    if sprite_name_map:
        name_map_path.write_text(
            json.dumps(sprite_name_map, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"  sprite_names: {len(sprite_name_map)} entries → {name_map_path.name}")

    # Generate .meta
    guid = stable_guid(f"cocos2unity:structural:{src_file.name}")
    if is_scene:
        meta_content = scene_meta(guid)
    else:
        meta_content = prefab_meta(guid)

    meta_path = dst_file.with_suffix(dst_file.suffix + ".meta")
    meta_path.write_text(meta_content, encoding="utf-8")

    return {
        "src": str(src_file),
        "dst": str(dst_file),
        "format": fmt,
        "node_count": plan.get("node_count", 0),
        "unknown_components": plan.get("unknown_components", []),
        "unity_guid": guid,
        "sprite_names_count": len(sprite_name_map),
    }


def batch_convert(src_dir: Path, dst_dir: Path, manifest: Dict[str, Any],
                  ppu: float, convert_pos: bool) -> Dict[str, Any]:
    """Scan src_dir for all .prefab / .scene / .fire files and convert them."""
    results: List[Dict[str, Any]] = []
    errors: List[str] = []
    structural_exts = {".prefab", ".scene", ".fire"}

    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = [d for d in dirnames if d.lower() not in IGNORE_DIRS]
        dp = Path(dirpath)

        for fname in filenames:
            src_file = dp / fname
            ext = src_file.suffix.lower()
            if ext not in structural_exts:
                continue

            rel = src_file.relative_to(src_dir)

            if ext in (".scene", ".fire"):
                out_name = rel.with_suffix(".unity")
            else:
                out_name = rel.with_suffix(".prefab")

            dst_file = dst_dir / out_name

            try:
                result = convert_single(src_file, dst_file, manifest, ppu, convert_pos)
                result["src_rel"] = rel.as_posix()
                result["dst_rel"] = out_name.as_posix()
                results.append(result)
                print(f"  OK {rel} -> {out_name} "
                      f"(nodes={result['node_count']}, fmt={result['format']})")

            except Exception as e:
                errors.append(f"{rel}: {e}")
                print(f"  ERROR {rel}: {e}", file=sys.stderr)

    summary = {
        "total_converted": len(results),
        "total_errors": len(errors),
        "prefabs": sum(1 for r in results if r["dst_rel"].endswith(".prefab")),
        "scenes": sum(1 for r in results if r["dst_rel"].endswith(".unity")),
        "results": results,
        "errors": errors,
    }

    return summary


# =====================================================================
# CLI
# =====================================================================

def main() -> int:
    # Ensure utf-8 output on Windows (for Chinese path names etc.)
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="Phase 2+: Batch-convert Cocos prefabs/scenes to Unity native .prefab/.unity YAML (v3 — full property mapping)"
    )
    ap.add_argument("--src", help="Cocos assets/ directory (batch mode)")
    ap.add_argument("--dst", help="Unity Assets/_Ported/ directory (batch mode)")
    ap.add_argument("--src-file", help="Single source file (single mode)")
    ap.add_argument("--dst-file", help="Single output file (single mode)")
    ap.add_argument("--manifest", required=True, help="manifest.json from Phase 1")
    ap.add_argument("--ppu", type=float, default=100, help="Pixels per unit (default: 100)")
    ap.add_argument("--convert-pos", action="store_true",
                    help="Divide positions by PPU for Unity world units")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    # Auto-scan script mappings from source Cocos project
    if args.src_file:
        ensure_script_mappings(Path(args.src_file))
    elif args.src:
        ensure_script_mappings(Path(args.src))

    # Auto-scan script GUIDs from destination Unity project if provided

    if args.dst:
        _scan_script_guids(Path(args.dst).parent)
    elif args.dst_file:
        _scan_script_guids(Path(args.dst_file).parent.parent) # Assuming Assets/_Ported/subdir/file.prefab

    if args.src_file and args.dst_file:

        result = convert_single(
            Path(args.src_file), Path(args.dst_file),
            manifest, args.ppu, args.convert_pos
        )
        print(f"OK nodes={result['node_count']} format={result['format']} "
              f"out={args.dst_file}")
        return 0

    if args.src and args.dst:
        src = Path(args.src).resolve()
        dst = Path(args.dst).resolve()
        if not src.is_dir():
            print(f"ERROR: src not a directory: {src}", file=sys.stderr)
            return 2

        summary = batch_convert(src, dst, manifest, args.ppu, args.convert_pos)
        print(f"\nBatch complete: "
              f"prefabs={summary['prefabs']} scenes={summary['scenes']} "
              f"errors={summary['total_errors']}")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
