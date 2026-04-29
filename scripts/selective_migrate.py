#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
selective_migrate.py
Selective migration with recursive dependency scanning.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import shutil
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from migrate_assets import (
    TEXTURE_EXT, AUDIO_EXT, FONT_EXT, PASSTHRU_EXT, STRUCTURAL_EXT,
    stable_guid, find_cocos_uuid, find_all_cocos_uuids,
    extract_9slice, meta_for, folder_meta,
)
from convert_scene import load_cocos, detect_format, deref

IGNORE_DIRS = {"temp", "library", "build", "node_modules", ".git", "local", "__pycache__", ".vscode", ".idea", "dist"}

def analyse_dependencies(target_file: Path, cocos_root: Path, strip_sdk: bool = False) -> Dict[str, Any]:
    data = load_cocos(target_file)
    fmt = detect_format(data)
    uuids, paths, nested_prefabs, scripts = set(), set(), set(), set()
    _collect_refs_recursive(data, uuids, paths, nested_prefabs, scripts, data)
    if fmt == "2.x":
        items = data if isinstance(data, list) else [data]
        for obj in items:
            if not isinstance(obj, dict) or obj.get("__type__") != "cc.Node": continue
            pref = obj.get("_prefab")
            if pref:
                pinfo = deref(data, pref)
                if isinstance(pinfo, dict) and pinfo.get("sync") and pinfo.get("asset"):
                    asset_uuid = pinfo["asset"].get("__uuid__")
                    if asset_uuid: uuids.add(asset_uuid)
    return {"target": str(target_file.relative_to(cocos_root)) if target_file.is_relative_to(cocos_root) else str(target_file), "format": fmt, "uuids_referenced": uuids, "paths_referenced": paths, "nested_prefabs": nested_prefabs, "scripts_referenced": scripts}

def _collect_refs_recursive(obj, uuids, paths, nested_prefabs, scripts, data, _depth=0):
    if _depth > 30: return
    if isinstance(obj, dict):
        for k in ("__uuid__", "_uuid", "uuid"):
            v = obj.get(k); 
            if isinstance(v, str) and len(v) > 4: uuids.add(v)
        if "__id__" in obj and len(obj) == 1:
            idx = obj["__id__"]
            if isinstance(idx, int) and 0 <= idx < len(data) and isinstance(data, list):
                t = data[idx]
                if isinstance(t, dict):
                    for k in ("__uuid__", "_uuid", "uuid"):
                        v = t.get(k)
                        if isinstance(v, str) and len(v) > 4: uuids.add(v)
                    for k in ("_nativeUrl", "_native", "_nativeAsset", "_N$file", "_rawUrl"):
                        pv = t.get(k)
                        if isinstance(pv, str) and len(pv) > 1: paths.add(pv)
            return
        for k in ("_nativeUrl", "_native", "_nativeAsset", "_N$file", "_rawUrl", "_name"):
            v = obj.get(k)
            if isinstance(v, str) and ("." in v or "/" in v or "\\" in v): paths.add(v)
        t = obj.get("__type__", "")
        if isinstance(t, str) and t and not t.startswith("cc.") and not t.startswith("sp."): scripts.add(t)
        for k, v in obj.items():
            if k.startswith("__") and k != "__type__" and k != "__uuid__": continue
            _collect_refs_recursive(v, uuids, paths, nested_prefabs, scripts, data, _depth + 1)
    elif isinstance(obj, list):
        for item in obj: _collect_refs_recursive(item, uuids, paths, nested_prefabs, scripts, data, _depth + 1)

def build_selective_manifest(cocos_assets, all_uuids, all_paths, strip_sdk=False):
    uuid_to_file, path_to_uuid = {}, {}
    for dp, dns, fns in os.walk(cocos_assets):
        dns[:] = [d for d in dns if d.lower() not in IGNORE_DIRS]
        for fn in fns:
            f = Path(dp) / fn
            if f.suffix.lower() == ".meta" or f.suffix.lower() in (".ts", ".js"): continue
            rel = f.relative_to(cocos_assets).as_posix()
            path_to_uuid[rel] = path_to_uuid[rel.lower()] = path_to_uuid[fn.lower()] = ""
            st = Path(fn).stem
            if len(st) > 2: path_to_uuid[st.lower()] = ""
            all_u = find_all_cocos_uuids(f.with_suffix(f.suffix + ".meta"))
            pri = None
            for u in all_u:
                uid = u["uuid"]; uuid_to_file[uid] = f
                if u["type"] == "main": pri = uid
                path_to_uuid[rel] = path_to_uuid[rel.lower()] = path_to_uuid[fn.lower()] = pri or uid
                if len(st) > 2: path_to_uuid[st.lower()] = pri or uid
    res_uuids = set(all_uuids)
    for p in all_paths:
        n = p.replace("\\", "/")
        for pref in ("db://assets/", "db://internal/", "resources/", "assets/", "db://"):
            if n.startswith(pref): n = n[len(pref):]; break
        for c in (n, n.lower(), Path(n).name.lower(), Path(n).stem.lower()):
            if c in path_to_uuid and path_to_uuid[c]: res_uuids.add(path_to_uuid[c]); break
    files = set()
    for u in res_uuids:
        if u in uuid_to_file: files.add(uuid_to_file[u])
        elif len(u) >= 8:
            for fu, fp in uuid_to_file.items():
                if fu.startswith(u) or u.startswith(fu): files.add(fp); break
    structural_to_scan = {f for f in files if f.suffix.lower() in STRUCTURAL_EXT}
    manifest = {"version": 2, "entries": [], "src": str(cocos_assets), "selective": True}
    seen = set()
    for f in sorted(files):
        ext, rel = f.suffix.lower(), f.relative_to(cocos_assets).as_posix()
        uid = find_cocos_uuid(f.with_suffix(f.suffix + ".meta"))
        guid = stable_guid(uid or f"cocos2unity:{rel}")
        entry = {"src": rel, "dst": (None if ext in STRUCTURAL_EXT else rel), "cocos_uuid": uid, "unity_guid": guid, "kind": ext.lstrip(".")}
        if ext in STRUCTURAL_EXT: entry["structural"] = True
        elif ext in TEXTURE_EXT:
            b = extract_9slice(f.with_suffix(f.suffix + ".meta"))
            if b and any(v > 0 for v in b.values()): entry["border_9slice"] = b
        manifest["entries"].append(entry); seen.add(guid)
        if ext in TEXTURE_EXT:
            for sub in find_all_cocos_uuids(f.with_suffix(f.suffix + ".meta")):
                if sub["uuid"] != uid and sub["uuid"] not in seen:
                    manifest["entries"].append({"src": rel, "dst": rel, "cocos_uuid": sub["uuid"], "unity_guid": guid, "kind": f"sub:{sub['type']}"})
    return manifest, files, structural_to_scan

def copy_selective_assets(cocos_assets, unity_ported, files, manifest, dry_run):
    copied, skipped, errors, created = 0, 0, 0, set()
    for f in sorted(files):
        ext, rel = f.suffix.lower(), f.relative_to(cocos_assets).as_posix()
        if ext in STRUCTURAL_EXT: skipped += 1; continue
        target = unity_ported / rel
        guid, border = "", None
        for e in manifest["entries"]:
            if e.get("src") == rel and not e.get("kind","").startswith("sub:"):
                guid, border = e.get("unity_guid"), e.get("border_9slice"); break
        if dry_run: copied += 1; continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            target.with_suffix(target.suffix + ".meta").write_text(meta_for(ext, guid, border), encoding="utf-8")
            copied += 1
        except: errors += 1
    return {"copied": copied, "skipped": skipped, "errors": errors}

def convert_selective_targets(targets, cocos_root, unity_ported, manifest, ppu, convert_pos):
    from convert_prefab import convert_single
    results = []
    for t in targets:
        ext = t.suffix.lower()
        sub = "_Scenes" if ext in (".scene", ".fire") else "_Prefabs"
        rel = t.relative_to(cocos_root / "assets") if t.is_relative_to(cocos_root / "assets") else t.name
        dst = unity_ported / sub / (Path(rel).parent / (t.stem + (".unity" if ext in (".scene", ".fire") else ".prefab")))
        results.append(convert_single(t, dst, manifest, ppu, convert_pos))
    return {"total_converted": len(results)}

def selective_migrate(cocos_root, unity_root, targets, ppu=100, convert_pos=False, dry_run=False, strip_sdk=False, output_dir=None):
    out_dir, cocos_assets = output_dir or unity_root, cocos_root / "assets"
    if not cocos_assets.is_dir(): cocos_assets = cocos_root
    unity_ported = unity_root / "Assets" / "_Ported"
    target_files = []
    for t in targets:
        tn = t.replace("\\", "/")
        for c in (cocos_root / tn, cocos_assets / tn, Path(tn)):
            if c.is_file(): target_files.append(c.resolve()); break
        else:
            matches = list(cocos_root.glob(f"**/{tn.split('/')[-1]}"))
            if matches: target_files.append(matches[0].resolve())
    if not target_files: return {"error": "no_targets"}
    all_uuids, all_paths, all_scripts, scanned = set(), set(), set(), set()
    queue = list(target_files)
    while queue:
        tf = queue.pop(0)
        if tf in scanned: continue
        scanned.add(tf)
        deps = analyse_dependencies(tf, cocos_root, strip_sdk)
        all_uuids.update(deps["uuids_referenced"]); all_paths.update(deps["paths_referenced"]); all_scripts.update(deps["scripts_referenced"])
    final_uuids, final_paths, final_files = set(all_uuids), set(all_paths), set()
    while True:
        manifest, files, structural = build_selective_manifest(cocos_assets, final_uuids, final_paths, strip_sdk)
        new_struct = structural - scanned
        if not new_struct: final_files = files; break
        for sf in new_struct:
            scanned.add(sf); deps = analyse_dependencies(sf, cocos_root, strip_sdk)
            final_uuids.update(deps["uuids_referenced"]); final_paths.update(deps["paths_referenced"])
    manifest_path = out_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    copy_stats = copy_selective_assets(cocos_assets, unity_ported, final_files, manifest, dry_run)
    convert_res = convert_selective_targets(target_files, cocos_root, unity_ported, manifest, ppu, convert_pos)
    return {"manifest_path": str(manifest_path), "converted": convert_res['total_converted']}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cocos", required=True); ap.add_argument("--unity", required=True); ap.add_argument("--target", action="append", required=True)
    ap.add_argument("--ppu", type=float, default=100); ap.add_argument("--convert-pos", action="store_true")
    args = ap.parse_args()
    res = selective_migrate(Path(args.cocos).resolve(), Path(args.unity).resolve(), args.target, args.ppu, args.convert_pos)
    print(f"Done. Manifest at {res.get('manifest_path')}")

if __name__ == "__main__": main()
