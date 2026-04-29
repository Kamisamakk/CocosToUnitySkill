#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
convert_scene.py
Phase 2: parse a Cocos Creator scene or prefab and produce a Unity "plan.json"
describing the GameObjects + components to create.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------- Cocos → Unity Component Map ----------
# ... (existing COMPONENT_MAP)
COMPONENT_MAP: Dict[str, Any] = {
    "cc.UITransform": {"component": "RectTransform", "fields": ["contentSize", "anchorPoint"]},
    "cc.Sprite": {"component": "UnityEngine.UI.Image", "fields": ["spriteFrame", "color", "type", "sizeMode", "fillType", "fillCenter", "fillStart", "fillRange", "trim", "grayscale", "material"]},
    "cc.Label": {"component": "UnityEngine.UI.Text", "fields": ["string", "fontSize", "color", "fontFamily", "font", "horizontalAlign", "verticalAlign", "overflow", "lineHeight", "enableBold", "enableItalic", "enableUnderline", "cacheMode", "material"]},
    "cc.LabelOutline": {"component": "UnityEngine.UI.Outline", "fields": ["color", "width"]},
    "cc.RichText": {"component": "UnityEngine.UI.Text", "fields": ["string", "fontSize", "maxWidth", "font", "color"]},

    "cc.Button": {"component": "UnityEngine.UI.Button", "fields": ["interactable", "transition", "normalColor", "pressedColor", "hoverColor", "disabledColor", "normalSprite", "pressedSprite", "clickEvents", "duration", "zoomScale"]},
    "cc.Toggle": {"component": "UnityEngine.UI.Toggle", "fields": ["isChecked", "checkMark", "interactable", "transition", "checkEvents"]},
    "cc.ToggleContainer": {"component": "UnityEngine.UI.ToggleGroup", "fields": ["allowSwitchOff"]},
    "cc.EditBox": {"component": "UnityEngine.UI.InputField", "fields": ["string", "placeholder", "placeholderLabel", "maxLength", "inputMode", "inputFlag", "returnType"]},
    "cc.Slider": {"component": "UnityEngine.UI.Slider", "fields": ["progress", "direction", "reverse"]},
    "cc.ProgressBar": {"component": "UnityEngine.UI.Slider", "fields": ["progress", "mode", "barSprite", "totalLength"]},
    "cc.ScrollView": {"component": "UnityEngine.UI.ScrollRect", "fields": ["horizontal", "vertical", "content", "brake", "bounceDuration", "elastic", "cancelInnerEvents"]},
    "cc.Layout": {"component": "__layout__", "fields": ["type", "spacingX", "spacingY", "paddingTop", "paddingBottom", "paddingLeft", "paddingRight", "resizeMode", "horizontalDirection", "verticalDirection"]},
    "cc.Mask": {"component": "__mask__", "fields": ["type", "spriteFrame", "alphaThreshold", "inverted"]},
    "cc.Canvas": {"component": "Canvas", "fields": ["designResolution", "fitWidth", "fitHeight"]},
    "cc.Widget": {"component": "__widget__", "fields": ["isAlignTop", "isAlignBottom", "isAlignLeft", "isAlignRight", "isAlignHorizontalCenter", "isAlignVerticalCenter", "top", "bottom", "left", "right", "horizontalCenter", "verticalCenter"]},
    "cc.UIOpacity": {"component": "CanvasGroup", "fields": ["opacity"]},
    "cc.BlockInputEvents": {"component": "CanvasGroup", "fields": []},
    "cc.Camera": {"component": "Camera", "fields": ["clearFlags", "backgroundColor", "orthoHeight", "depth", "projection", "fov", "near", "far", "rect", "visibility"]},

    "cc.SpriteRenderer": {"component": "SpriteRenderer", "fields": ["sprite", "color", "flipX", "flipY", "material"]},
    "cc.ParticleSystem2D": {"component": "ParticleSystem", "fields": []},
    "cc.AudioSource": {"component": "AudioSource", "fields": ["clip", "volume", "loop", "playOnAwake", "pitch"]},
    "cc.Animation": {"component": "Animator", "fields": ["defaultClip", "clips"]},
    "cc.RigidBody2D": {"component": "Rigidbody2D", "fields": ["bodyType", "gravityScale", "linearDamping", "angularDamping", "fixedRotation", "allowSleep"]},
    "cc.BoxCollider2D": {"component": "BoxCollider2D", "fields": ["size", "offset", "isTrigger"]},
    "cc.CircleCollider2D": {"component": "CircleCollider2D", "fields": ["radius", "offset", "isTrigger"]},
    "cc.PolygonCollider2D": {"component": "PolygonCollider2D", "fields": ["points", "isTrigger"]},
    "sp.Skeleton": {"component": "Spine.Unity.SkeletonAnimation", "fields": ["skeletonData", "defaultSkin", "defaultAnimation", "loop", "premultipliedAlpha"]},
    "dragonBones.ArmatureDisplay": {"component": "DragonBones.UnityArmatureComponent", "fields": ["dragonAsset", "dragonAtlasAsset", "armatureName", "animationName", "playTimes", "timeScale"]},
}

# Map Cocos UUID scripts to human-readable C# class names (populated by scanning library/imports)
UUID_SCRIPT_MAP: Dict[str, str] = {}



def _scan_cocos_library(cocos_project_dir: Path):
    """Scan Cocos library/imports for .js files and extract uuid -> script name mapping."""
    global UUID_SCRIPT_MAP
    lib_path = cocos_project_dir / "library" / "imports"
    if not lib_path.exists():
        return
    
    print(f"Scanning Cocos library for script mappings in {lib_path}...")
    # Pattern: cc._RF.push(module, 'compressed_uuid', 'ClassName');
    pattern = re.compile(r"cc\._RF\.push\(module,\s*'([^']+)',\s*'([^']+)'\);")
    count = 0
    for js_file in lib_path.rglob("*.js"):
        try:
            content = js_file.read_text(encoding="utf-8")
            match = pattern.search(content)
            if match:
                compressed_uuid = match.group(1)
                class_name = match.group(2)
                if compressed_uuid not in UUID_SCRIPT_MAP:
                    UUID_SCRIPT_MAP[compressed_uuid] = class_name
                    count += 1
        except Exception:
            pass
    
    if count > 0:
        print(f"  Found {count} new script mappings from library.")


def ensure_script_mappings(src_file: Path):
    """Ensure UUID_SCRIPT_MAP is populated by scanning the project from a source file path."""
    cocos_project_dir = src_file.parent
    while cocos_project_dir.name.lower() != 'assets' and cocos_project_dir.parent != cocos_project_dir:
        cocos_project_dir = cocos_project_dir.parent
    if cocos_project_dir.name.lower() == 'assets':
        _scan_cocos_library(cocos_project_dir.parent)




def load_cocos(path: Path) -> Any:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    return data


def detect_format(data: Any) -> str:
    has_3x, has_2x = False, False
    # If it's a single object, wrap in a list for uniform processing
    items = data if isinstance(data, list) else [data]
    for obj in items:
        if not isinstance(obj, dict): continue

        if obj.get("__type__") == "cc.Node":
            if "_lpos" in obj or "_lrot" in obj: has_3x = True
            if "_position" in obj or "_contentSize" in obj: has_2x = True
            if has_3x and not has_2x: return "3.x"
            if has_2x and not has_3x: return "2.x"
    return "3.x" if has_3x else "2.x"

def deref(data: List[dict], entry: Any) -> Any:
    if isinstance(entry, dict) and "__id__" in entry and len(entry) == 1:
        idx = entry["__id__"]
        if 0 <= idx < len(data): return data[idx]
    return entry

def _resolve_cocos_path(src_file: Path, cocos_rel_path: str) -> Optional[Path]:
    p = src_file.parent
    while p.name.lower() != 'assets' and p.parent != p: p = p.parent
    if p.name.lower() == 'assets':
        target = p / cocos_rel_path
        if target.exists(): return target
        if cocos_rel_path.startswith('assets/'):
            target = p.parent / cocos_rel_path
            if target.exists(): return target
    return None

def _expand_synced_prefabs(data: List[dict], manifest: Dict[str, Any], src_file: Path) -> List[dict]:
    new_data = list(data)
    uuid_to_entry = {e['cocos_uuid']: e for e in manifest.get('entries', []) if e.get('cocos_uuid')}
    to_expand = []
    for i, obj in enumerate(new_data):
        if not isinstance(obj, dict) or obj.get("__type__") != "cc.Node": continue
        pref = obj.get("_prefab")
        if pref:
            pinfo = deref(new_data, pref)
            if isinstance(pinfo, dict) and pinfo.get("sync") and pinfo.get("asset"):
                uuid = pinfo["asset"].get("__uuid__")
                if uuid: to_expand.append((i, uuid))
    if not to_expand: return new_data

    for node_idx, uuid in to_expand:
        entry = uuid_to_entry.get(uuid)
        if not entry or not entry.get('src'): continue
        path = _resolve_cocos_path(src_file, entry['src'])
        if not path: continue
        try:
            prefab_data = load_cocos(path)
            root_idx = -1
            for j, pobj in enumerate(prefab_data):
                if pobj.get("__type__") == "cc.Node" and pobj.get("_parent") is None:
                    root_idx = j; break
            if root_idx == -1: continue

            id_map = {}
            id_offset = len(new_data)
            for j, pobj in enumerate(prefab_data):
                if j == root_idx: id_map[j] = node_idx
                else:
                    id_map[j] = len(new_data)
                    new_data.append(json.loads(json.dumps(pobj)))

            # Copy components and children from prefab root to instance
            root_node = prefab_data[root_idx]
            instance = new_data[node_idx]
            
            # Merge children
            if not instance.get("_children") and root_node.get("_children"):
                instance["_children"] = json.loads(json.dumps(root_node["_children"]))
            
            # Merge components
            if not instance.get("_components") and root_node.get("_components"):
                instance["_components"] = json.loads(json.dumps(root_node["_components"]))
            
            # Fallback transform
            for attr in ("_trs", "_position", "_scaleX", "_scaleY", "_rotationX", "_rotationY", "_anchorPoint", "_contentSize"):
                if instance.get(attr) is None and root_node.get(attr) is not None:
                    instance[attr] = json.loads(json.dumps(root_node[attr]))


            def _update_ids(val):
                if isinstance(val, dict):
                    if "__id__" in val: val["__id__"] = id_map.get(val["__id__"], val["__id__"])
                    else:
                        for k in val: _update_ids(val[k])
                elif isinstance(val, list):
                    for item in val: _update_ids(item)

            for k in range(id_offset, len(new_data)): _update_ids(new_data[k])
            if "_children" in instance: _update_ids(instance["_children"])
            if "_components" in instance: _update_ids(instance["_components"])

            for child_ref in instance.get("_children", []):
                idx = child_ref.get("__id__")
                if idx is not None and idx < len(new_data):
                    if isinstance(new_data[idx], dict): new_data[idx]["_parent"] = {"__id__": node_idx}
        except Exception as e: print(f"Warning: Prefab expansion failed for {uuid}: {e}")
    return new_data

def _extract_src_name(data: List[dict], val: Any, _visited=None) -> Optional[str]:
    if val is None or isinstance(val, str): return None
    if _visited is None: _visited = set()
    if isinstance(val, dict):
        if "__uuid__" in val and "__id__" not in val: return None
        if "__id__" in val:
            idx = val["__id__"]
            if idx in _visited: return None
            _visited.add(idx)
            if 0 <= idx < len(data):
                res = data[idx]
                if not isinstance(res, dict): return None
                for k in ("_nativeUrl", "_native", "_nativeAsset", "_N$file", "_rawUrl", "_name"):
                    pv = res.get(k)
                    if pv and isinstance(pv, str) and len(pv) > 1:
                        from pathlib import PurePosixPath
                        name = PurePosixPath(pv.replace("\\", "/")).name
                        if name and ("." in name or k == "_name"): return name
                for k in ("_spriteFrame", "_clip", "_skeleton", "_dragonBone", "_texture", "_font"):
                    sub = res.get(k)
                    if sub:
                        r = _extract_src_name(data, sub, _visited)
                        if r: return r
    return None

def _deep_resolve_asset_ref(data: List[dict], val: Any, uuid_to_guid: Dict[str, str], _visited=None) -> Any:
    if val is None or isinstance(val, str): return val
    if _visited is None: _visited = set()
    if isinstance(val, dict):
        if "__uuid__" in val:
            if "_src_name" not in val:
                src = _extract_src_name(data, val, set())
                if src: return {**val, "_src_name": src}
            return val
        if "__id__" in val:
            idx = val["__id__"]
            if idx in _visited: return {"__id__": idx, "_unresolved": True}
            _visited.add(idx)
            src_name = _extract_src_name(data, val, set())
            if 0 <= idx < len(data):
                res = data[idx]
                if isinstance(res, dict):
                    for k in ("__uuid__", "_uuid", "uuid"):
                        if k in res and isinstance(res[k], str):
                            ret = {"__uuid__": res[k]}
                            if src_name: ret["_src_name"] = src_name
                            return ret
                    for k in ("_nativeUrl", "_native", "_name", "_rawUrl"):
                        pv = res.get(k)
                        if pv and isinstance(pv, str):
                            uid = _find_uuid_by_path(pv, uuid_to_guid)
                            if uid: return {"__uuid__": uid, "_src_name": src_name or pv}
                    for k in ("_spriteFrame", "_clip", "_skeleton", "_texture", "_font"):
                        sub = res.get(k)
                        if sub:
                            r = _deep_resolve_asset_ref(data, sub, uuid_to_guid, _visited)
                            if r and not (isinstance(r, dict) and r.get("_unresolved")): return r
            return {"__id__": idx, "_unresolved": True, "_src_name": src_name} if src_name else {"__id__": idx, "_unresolved": True}
    return val

_global_path_to_uuid: Dict[str, str] = {}
def _find_uuid_by_path(path: str, uuid_to_guid, ext_filter=()):
    global _global_path_to_uuid
    if not path or not _global_path_to_uuid: return None
    p = path.replace("\\", "/")
    for pref in ("db://assets/", "db://internal/", "resources/", "assets/", "db://"):
        if p.startswith(pref): p = p[len(pref):]; break
    if p in _global_path_to_uuid: return _global_path_to_uuid[p]
    from pathlib import PurePosixPath
    n = PurePosixPath(p).name
    if n in _global_path_to_uuid: return _global_path_to_uuid[n]
    s = PurePosixPath(p).stem
    if s in _global_path_to_uuid and len(s) > 3: return _global_path_to_uuid[s]
    return None

def _quat_to_euler(qx, qy, qz, qw):
    r = math.atan2(2*(qw*qx+qy*qz), 1-2*(qx*qx+qy*qy))
    p = math.asin(max(-1, min(1, 2*(qw*qy-qz*qx))))
    y = math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz))
    return (math.degrees(r), math.degrees(p), math.degrees(y))

def extract_widget_anchors(comp, node_anchor=(0.5,0.5)):
    res = {"type": "widget_to_anchors"}
    f = {k: comp.get(k) or comp.get(f"_{k}") for k in ["isAlignTop", "isAlignBottom", "isAlignLeft", "isAlignRight", "isAlignHorizontalCenter", "isAlignVerticalCenter"]}
    o = {k: comp.get(k) or comp.get(f"_{k}") for k in ["top", "bottom", "left", "right", "horizontalCenter", "verticalCenter"] if (comp.get(k) or comp.get(f"_{k}")) is not None}
    ax, ay = node_anchor
    minx = maxx = ax; miny = maxy = ay
    if f["isAlignLeft"] and f["isAlignRight"]: minx, maxx = 0, 1
    elif f["isAlignLeft"]: minx = maxx = 0
    elif f["isAlignRight"]: minx = maxx = 1
    elif f["isAlignHorizontalCenter"]: minx = maxx = 0.5
    if f["isAlignTop"] and f["isAlignBottom"]: miny, maxy = 0, 1
    elif f["isAlignBottom"]: miny = maxy = 0
    elif f["isAlignTop"]: miny = maxy = 1
    elif f["isAlignVerticalCenter"]: miny = maxy = 0.5
    res.update({"anchorMin": [minx, miny], "anchorMax": [maxx, maxy], "offsets": o, "flags": f})
    return res

def resolve_layout_type(comp):
    t = 0
    for k in ("layoutType", "_layoutType", "_N$layoutType", "type", "_type"):
        v = comp.get(k)
        if v is not None: t = int(v); break
    return {1: "HorizontalLayoutGroup", 2: "VerticalLayoutGroup", 3: "GridLayoutGroup"}.get(t, "VerticalLayoutGroup") if t > 0 else None

def build_plan_3x(data, manifest, ppu, convert_pos, src_file):
    global _global_path_to_uuid
    data = _expand_synced_prefabs(data, manifest, src_file)
    u2g = {e['cocos_uuid']: e.get('unity_guid','') for e in manifest.get('entries',[]) if e.get('cocos_uuid')}
    p2u = {}
    for e in manifest.get('entries',[]):
        s, c = e.get('src',''), e.get('cocos_uuid','')
        if s and c: p2u[s] = c; p2u[s.replace("\\","/")] = c; n = Path(s).name; p2u[n] = c; st = Path(s).stem
        if st and len(st)>3: p2u[st] = c
    _global_path_to_uuid = p2u
    
    node_by_idx = {i: obj for i, obj in enumerate(data) if isinstance(obj, dict) and obj.get("__type__") == "cc.Node"}
    effective_colors = {}

    def get_effective_color(idx):
        if idx in effective_colors: return effective_colors[idx]
        obj = node_by_idx.get(idx)
        if not obj: return {"r": 255, "g": 255, "b": 255, "a": 255}
        c = obj.get("_color")
        self_color = {"r": c.get("r", 255), "g": c.get("g", 255), "b": c.get("b", 255), "a": 255} if c else {"r": 255, "g": 255, "b": 255, "a": 255}
        self_opacity = obj.get("_opacity", 255)
        if self_opacity is None: self_opacity = 255
        self_color["a"] = self_opacity
        p = obj.get("_parent")
        pidx = p["__id__"] if isinstance(p, dict) and "__id__" in p else None
        if pidx is not None and pidx in node_by_idx:
            pc = get_effective_color(pidx)
            self_color = {"r": int(self_color["r"] * pc["r"] / 255.0), "g": int(self_color["g"] * pc["g"] / 255.0), "b": int(self_color["b"] * pc["b"] / 255.0), "a": int(self_color["a"] * pc["a"] / 255.0)}
        effective_colors[idx] = self_color
        return self_color

    nodes, unknown = [], []
    for i, obj in enumerate(data):
        if not isinstance(obj, dict) or obj.get("__type__") != "cc.Node": continue
        p = obj.get("_parent")
        pidx = p["__id__"] if isinstance(p, dict) and "__id__" in p else None
        pos, rot, sc, eul = obj.get("_lpos",{}), obj.get("_lrot",{}), obj.get("_lscale",{}), obj.get("_euler",{})
        px, py, pz = pos.get("x",0), pos.get("y",0), pos.get("z",0)
        ex, ey, ez = eul.get("x",0), eul.get("y",0), eul.get("z",0)
        if ex==0 and ey==0 and ez==0 and rot:
            ex, ey, ez = _quat_to_euler(rot.get("x",0), rot.get("y",0), rot.get("z",0), rot.get("w",1))
        c_raw = obj.get("_components",[]) or []
        comps = _resolve_components(data, c_raw, unknown, u2g, p2u)
        ec = get_effective_color(i)
        node = {"index": i, "name": obj.get("_name",f"Node_{i}"), "active": obj.get("_active",True), "parent_index": pidx, "z_order": obj.get("_localZOrder",0), "transform": {"position": [px,py,pz], "euler": [ex,ey,ez], "scale": [sc.get("x",1), sc.get("y",1), sc.get("z",1)]}, "components": comps, "color": ec, "opacity": ec["a"]}
        nodes.append(node)
    return _finalize_plan(nodes, unknown, u2g, "3.x")

def build_plan_2x(data, manifest, ppu, convert_pos, src_file):
    global _global_path_to_uuid
    data = _expand_synced_prefabs(data, manifest, src_file)
    u2g = {e['cocos_uuid']: e.get('unity_guid','') for e in manifest.get('entries',[]) if e.get('cocos_uuid')}
    p2u = {}
    for e in manifest.get('entries',[]):
        s, c = e.get('src',''), e.get('cocos_uuid','')
        if s and c: p2u[s] = c; p2u[s.replace("\\","/")] = c; n = Path(s).name; p2u[n] = c; st = Path(s).stem
        if st and len(st)>3: p2u[st] = c
    _global_path_to_uuid = p2u
    node_by_idx = {i: obj for i, obj in enumerate(data) if isinstance(obj, dict) and obj.get("__type__") == "cc.Node"}
    effective_colors = {}

    def get_effective_color(idx):
        if idx in effective_colors: return effective_colors[idx]
        obj = node_by_idx.get(idx)
        if not obj: return {"r": 255, "g": 255, "b": 255, "a": 255}
        c = obj.get("_color")
        self_color = {"r": c.get("r", 255), "g": c.get("g", 255), "b": c.get("b", 255), "a": 255} if c else {"r": 255, "g": 255, "b": 255, "a": 255}
        self_opacity = obj.get("_opacity", 255)
        if self_opacity is None: self_opacity = 255
        self_color["a"] = self_opacity
        p = obj.get("_parent")
        pidx = p["__id__"] if isinstance(p, dict) and "__id__" in p else None
        if pidx is not None and pidx in node_by_idx:
            pc = get_effective_color(pidx)
            self_color = {"r": int(self_color["r"] * pc["r"] / 255.0), "g": int(self_color["g"] * pc["g"] / 255.0), "b": int(self_color["b"] * pc["b"] / 255.0), "a": int(self_color["a"] * pc["a"] / 255.0)}
        effective_colors[idx] = self_color
        return self_color

    nodes, unknown = [], []
    for i, obj in enumerate(data):
        if not isinstance(obj, dict) or obj.get("__type__") != "cc.Node": continue
        p = obj.get("_parent")
        pidx = p["__id__"] if isinstance(p, dict) and "__id__" in p else None
        trs = obj.get("_trs")
        if isinstance(trs, dict) and trs.get("__type__") == "TypedArray":
            a = trs.get("array", [])
            px, py, pz = (a[0], a[1], a[2]) if len(a)>=3 else (0,0,0)
            rz = -math.degrees(math.atan2(2*(a[6]*a[5]+a[3]*a[4]), 1-2*(a[4]*a[4]+a[5]*a[5]))) if len(a)>=7 else 0
            sx, sy = (a[7], a[8]) if len(a)>=9 else (1,1)
        else:
            pos = deref(data, obj.get("_position",{}))
            if not isinstance(pos, dict): pos = {}
            px, py, pz = pos.get("x",0), pos.get("y",0), 0
            sx, sy = obj.get("_scaleX",1), obj.get("_scaleY",1)
            rx, ry = obj.get("_rotationX",0), obj.get("_rotationY",0)
            rz = rx if rx==ry else (rx+ry)/2.0
        anc, cs = deref(data, obj.get("_anchorPoint",{})), deref(data, obj.get("_contentSize",{}))
        if not isinstance(anc, dict): anc = {}
        if not isinstance(cs, dict): cs = {}
        comps = _resolve_components(data, obj.get("_components",[]) or [], unknown, u2g, p2u, node_obj=obj)
        w, h = cs.get("width",0), cs.get("height",0)
        ax, ay = anc.get("x",0.5), anc.get("y",0.5)
        if w>0 or h>0 or abs(ax-0.5)>1e-6 or abs(ay-0.5)>1e-6:
            comps.insert(0, {"cocos_type": "cc.UITransform", "unity_component": "RectTransform", "fields": {"contentSize": {"width": w, "height": h}, "anchorPoint": {"x": ax, "y": ay}}})
        ec = get_effective_color(i)
        node = {"index": i, "name": obj.get("_name",f"Node_{i}"), "active": obj.get("_active",True), "parent_index": pidx, "z_order": obj.get("_localZOrder",0), "transform": {"position": [px,py,pz], "euler": [0,0,-rz], "scale": [sx,sy,1]}, "components": comps, "color": ec, "opacity": ec["a"]}
        nodes.append(node)
    return _finalize_plan(nodes, unknown, u2g, "2.x")

def _resolve_components(data, raw, unknown, u2g, p2u, node_obj=None):
    ASSET_REFS = {"spriteFrame", "font", "clip", "defaultClip", "normalSprite", "pressedSprite", "barSprite", "checkMark", "skeletonData", "dragonAsset", "dragonAtlasAsset", "tmxAsset", "sprite", "content", "material", "placeholderLabel"}
    res = []
    for c in raw:
        comp = deref(data, c)
        if not isinstance(comp, dict): continue
        t = comp.get("__type__","")
        m = COMPONENT_MAP.get(t)
        if m is None:
            if not t.startswith("cc.") and not t.startswith("sp."):
                unity_name = UUID_SCRIPT_MAP.get(t, t.split(".")[-1])
                f = {k: (_deep_resolve_asset_ref(data, v, u2g) if isinstance(v, dict) and ("__id__" in v or "__uuid__" in v) else v) for k, v in comp.items() if not k.startswith("__")}
                res.append({"cocos_type": t, "unity_component": unity_name, "note": "Custom", "fields": f})
            else: unknown.append(t); res.append({"cocos_type": t, "unity_component": None, "note": "UNMAPPED", "raw_fields": {k: v for k, v in comp.items() if k not in ("__type__","__prefab__","__id__")}})
            continue

        cname = m["component"] if isinstance(m, dict) else m
        if cname == "__mask__":
            sf = comp.get("_spriteFrame") or comp.get("spriteFrame")
            cname = "SpriteMask" if (sf or int(comp.get("_type",0)) in (1,2)) else "UnityEngine.UI.RectMask2D"
        if cname == "__widget__":
            na = deref(data, node_obj.get("_anchorPoint",{})) if node_obj else {}
            res.append({"cocos_type": t, "unity_component": "RectTransform.anchors", "anchors": extract_widget_anchors(comp, (na.get("x",0.5), na.get("y",0.5)))})
            continue
        if cname is None: res.append({"cocos_type": t, "unity_component": None, "note": m.get("note")}); continue
        if t == "cc.Layout": cname = resolve_layout_type(comp); 
        if not cname: continue
        f = {}
        if isinstance(m, dict):
            for fn in m.get("fields", []):
                v = comp.get(fn) or comp.get(f"_{fn}") or comp.get(f"_N${fn}")
                if v is not None:
                    if fn in ASSET_REFS: v = _deep_resolve_asset_ref(data, v, u2g)
                    elif fn == "clips" and isinstance(v, list): v = [_deep_resolve_asset_ref(data, x, u2g) for x in v]
                    f[fn] = v
        res.append({"cocos_type": t, "unity_component": cname, "fields": f})
    return res

def _finalize_plan(nodes, unknown, u2g, ver):
    global _global_path_to_uuid
    u2s = {v: k for k, v in _global_path_to_uuid.items()}
    for n in nodes:
        for c in n.get("components",[]):
            for k, v in c.get("fields",{}).items():
                if isinstance(v, dict) and "_src_name" in v:
                    uid = v.get("__uuid__")
                    if uid: u2s[uid] = v["_src_name"]
    return {"format": "cocos2unity.plan.v3", "cocos_version": ver, "nodes": nodes, "node_count": len(nodes), "unknown_components": sorted(set(unknown)), "uuid_to_guid_size": len(u2g), "uuid_to_src": u2s}

def main():
    if sys.platform=="win32":
        try: sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
        except: pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--manifest", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--ppu", type=float, default=100); ap.add_argument("--convert-pos", action="store_true")
    args = ap.parse_args()
    src, mf = Path(args.src), json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    # Auto-scan Cocos library for script mappings
    ensure_script_mappings(src)

    data = load_cocos(src); fmt = detect_format(data)


    plan = build_plan_2x(data, mf, args.ppu, args.convert_pos, src) if fmt=="2.x" else build_plan_3x(data, mf, args.ppu, args.convert_pos, src)
    Path(args.out).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK format={fmt} nodes={plan['node_count']} out={args.out}")

if __name__ == "__main__": main()
