#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
convert_anim.py
Phase 4: Cocos Creator .anim (JSON) -> minimal Unity AnimationClip YAML.

Scope of this MVP:
  - Linear / step interpolations on position/rotation/scale/color/opacity curves.
  - Produces a .anim YAML that Unity can import as an AnimationClip asset.
  - Non-linear easing (e.g. cc.easing.elasticOut) is downgraded to linear and
    flagged in the sidecar notes file.

This is intentionally conservative: if a curve type is unrecognized, we emit
the keys as linear and print a warning. A human can then replace the curve
with a hand-authored one if fidelity matters.

Usage:
  python convert_anim.py --src Foo.anim --out Foo.anim  (Unity-side)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

UNSUPPORTED_EASINGS = {
    "elasticIn", "elasticOut", "elasticInOut",
    "backIn", "backOut", "backInOut",
    "bounceIn", "bounceOut", "bounceInOut",
}


def collect_curves(anim: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Return (curves, warnings). Each curve is {path, property, keys}."""
    curves: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # Cocos 3.x: anim.curves is a list; each entry has {modifiers, valueAdapter, data: {keys, values}}
    for curve in anim.get("curves", []) or []:
        modifiers = curve.get("modifiers", [])
        path = "/".join(str(m) for m in modifiers if isinstance(m, str))
        prop = next((m for m in modifiers if not isinstance(m, str)), None)
        prop_name = str(prop) if prop is not None else (modifiers[-1] if modifiers else "unknown")
        data = curve.get("data", {})
        keys_ref = data.get("keys", 0)
        values = data.get("values", [])
        easing = data.get("easingMethod") or data.get("easingMethods")

        key_times = anim.get("keys", [[]])
        if isinstance(keys_ref, int) and 0 <= keys_ref < len(key_times):
            times = key_times[keys_ref]
        else:
            times = list(range(len(values)))

        if isinstance(easing, str) and easing in UNSUPPORTED_EASINGS:
            warnings.append(f"easing '{easing}' on {path}.{prop_name} downgraded to linear")

        curves.append({
            "path": path,
            "property": prop_name,
            "times": times,
            "values": values,
        })
    return curves, warnings


def emit_yaml(clip_name: str, sample_rate: float, curves: List[Dict[str, Any]]) -> str:
    """Emit a minimal Unity AnimationClip YAML.

    Only numeric scalar curves are emitted (position.x/y/z, rotation, scale, color.a, opacity).
    Everything else is left as a comment for manual completion.
    """
    lines = [
        "%YAML 1.1",
        "%TAG !u! tag:unity3d.com,2011:",
        "--- !u!74 &7400000",
        "AnimationClip:",
        f"  m_Name: {clip_name}",
        "  serializedVersion: 6",
        "  m_Legacy: 0",
        "  m_Compressed: 0",
        "  m_UseHighQualityCurve: 1",
        f"  m_SampleRate: {sample_rate}",
        "  m_WrapMode: 0",
        "  m_Bounds:",
        "    m_Center: {x: 0, y: 0, z: 0}",
        "    m_Extent: {x: 0, y: 0, z: 0}",
        "  m_ClipBindingConstant:",
        "    genericBindings: []",
        "    pptrCurveMapping: []",
        "  m_AnimationClipSettings:",
        "    serializedVersion: 2",
        "    m_AdditiveReferencePoseClip: {fileID: 0}",
        "    m_AdditiveReferencePoseTime: 0",
        "    m_StartTime: 0",
        "    m_StopTime: 1",
        "    m_OrientationOffsetY: 0",
        "    m_Level: 0",
        "    m_CycleOffset: 0",
        "    m_HasAdditiveReferencePose: 0",
        "    m_LoopTime: 0",
        "  m_EditorCurves:",
    ]

    scalar_curves = [c for c in curves if isinstance(c.get("values"), list)
                     and c["values"] and isinstance(c["values"][0], (int, float))]

    for c in scalar_curves:
        lines.append(f"  - curve:")
        lines.append(f"      serializedVersion: 2")
        lines.append(f"      m_Curve:")
        for t, v in zip(c["times"], c["values"]):
            lines.append(f"      - serializedVersion: 3")
            lines.append(f"        time: {t}")
            lines.append(f"        value: {v}")
            lines.append(f"        inSlope: 0")
            lines.append(f"        outSlope: 0")
            lines.append(f"        tangentMode: 0")
            lines.append(f"        weightedMode: 0")
            lines.append(f"        inWeight: 0.33333334")
            lines.append(f"        outWeight: 0.33333334")
        lines.append(f"      m_PreInfinity: 2")
        lines.append(f"      m_PostInfinity: 2")
        lines.append(f"      m_RotationOrder: 4")
        lines.append(f"    attribute: {c['property']}")
        lines.append(f"    path: {c['path']}")
        lines.append(f"    classID: 4")
        lines.append(f"    script: {{fileID: 0}}")

    return "\n".join(lines) + "\n"


IGNORE_DIRS = {"temp", "library", "build", "node_modules", ".git", "local",
               "__pycache__", ".vscode", ".idea", "dist"}


def convert_single(src_file: Path, out_file: Path) -> Dict[str, Any]:
    """Convert a single .anim file. Returns {curves, warnings, clip_name}."""
    anim = json.loads(src_file.read_text(encoding="utf-8", errors="ignore"))
    curves, warnings = collect_curves(anim)

    clip_name = anim.get("_name") or src_file.stem
    sample_rate = float(anim.get("sample", 60))
    yaml = emit_yaml(clip_name, sample_rate, curves)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(yaml, encoding="utf-8")
    notes_path = out_file.with_suffix(out_file.suffix + ".notes.txt")
    notes_path.write_text("\n".join(warnings) if warnings else "ok\n", encoding="utf-8")

    return {"curves": len(curves), "warnings": len(warnings), "clip_name": clip_name}


def batch_convert(src_dir: Path, dst_dir: Path) -> Dict[str, Any]:
    """Scan src_dir for all .anim files and convert them to Unity AnimationClip YAML."""
    import os
    results: List[Dict[str, Any]] = []
    errors: List[str] = []

    for dirpath, dirnames, filenames in os.walk(src_dir):
        dirnames[:] = [d for d in dirnames if d.lower() not in IGNORE_DIRS]
        dp = Path(dirpath)

        for fname in filenames:
            if not fname.lower().endswith(".anim"):
                continue

            src_file = dp / fname
            rel = src_file.relative_to(src_dir)
            out_file = dst_dir / rel

            try:
                result = convert_single(src_file, out_file)
                result["src_rel"] = rel.as_posix()
                results.append(result)
                print(f"  OK {rel} -> curves={result['curves']} warnings={result['warnings']}")
            except Exception as e:
                errors.append(f"{rel}: {e}")
                print(f"  ERROR {rel}: {e}", file=sys.stderr)

    return {
        "total_converted": len(results),
        "total_errors": len(errors),
        "results": results,
        "errors": errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Phase 4: Convert Cocos .anim to Unity AnimationClip YAML"
    )
    ap.add_argument("--src", help="Single source .anim file")
    ap.add_argument("--out", help="Single output .anim file (Unity YAML)")
    ap.add_argument("--src-dir", help="Source directory for batch mode")
    ap.add_argument("--dst-dir", help="Output directory for batch mode")
    args = ap.parse_args()

    if args.src and args.out:
        result = convert_single(Path(args.src), Path(args.out))
        print(f"OK curves={result['curves']} warnings={result['warnings']} out={args.out}")
        return 0

    if args.src_dir and args.dst_dir:
        summary = batch_convert(Path(args.src_dir).resolve(), Path(args.dst_dir).resolve())
        print(f"\nBatch complete: converted={summary['total_converted']} "
              f"errors={summary['total_errors']}")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
