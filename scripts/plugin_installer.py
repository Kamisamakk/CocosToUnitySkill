#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
plugin_installer.py — Auto-install Unity plugins based on migration needs.

Detects what plugins are required by scanning translation notes (from ts_to_csharp.py)
or source files, then copies/installs the corresponding packages into the Unity project.

Currently supported:
  - DOTween Pro (.unitypackage) — when cc.tween usage is detected in source scripts
  - (Extensible: add more plugins here)

Usage (standalone):
  python plugin_installer.py --unity <unity-root> --src-dir <cocos-scripts-dir>

Usage (as module):
  from plugin_installer import install_plugins
  install_plugins(notes: List[str], unity_root: Path)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import List, Optional

# Where plugin packages are bundled alongside this script
SKILL_ASSETS = Path(__file__).parent.parent / "assets"


# =========================================================================
# Per-plugin installers — add new plugins here
# =========================================================================

def _install_dotween(unity_root: Path) -> bool:
    """Copy DOTween Pro.unitypackage to Unity project root. Returns True if installed."""
    pkg_name = "DOTween Pro.unitypackage"
    src = SKILL_ASSETS / pkg_name

    if not src.is_file():
        print(f"  WARNING: {pkg_name} not found at {src}", file=sys.stderr)
        print("  Download DOTween from Unity Asset Store or itch.io manually.", file=sys.stderr)
        return False

    dst = unity_root / pkg_name
    if dst.is_file():
        print(f"  [DOTween] Already present at {dst}")
        return False

    try:
        shutil.copy2(src, dst)
        print(f"  [DOTween] Installed → {dst}")
        print("            Open Unity → Assets > Import Package > Custom Package to import.")
        return True
    except Exception as e:
        print(f"  WARNING: Failed to copy DOTween: {e}", file=sys.stderr)
        return False


# =========================================================================
# Plugin registry — maps detection key → installer function
# =========================================================================

_PLUGINS = {
    "dotween": {
        "label": "DOTween",
        "key_note": "DOTween",       # present in ts_to_csharp notes
        "key_source": "cc.tween",    # present in source JS files
        "install": _install_dotween,
    },
    # Add more plugins here:
    # "probuilder": {
    #     "label": "ProBuilder",
    #     "key_source": "ProBuilder",
    #     "install": _install_probuilder,
    # },
}


# =========================================================================
# Core API
# =========================================================================

def detect_from_notes(notes: List[str]) -> List[str]:
    """Return list of plugin IDs that are required based on translation notes."""
    required = []
    for pid, plugin in _PLUGINS.items():
        if plugin["key_note"] and any(plugin["key_note"] in n for n in notes):
            required.append(pid)
    return required


def detect_from_source(src_dir: Path) -> List[str]:
    """Return list of plugin IDs required by scanning source JS/TS files."""
    required = []
    if not src_dir.is_dir():
        return required

    for ext in ("*.ts", "*.js"):
        for f in src_dir.rglob(ext):
            if f.name.endswith(".d.ts"):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            for pid, plugin in _PLUGINS.items():
                if pid in required:
                    continue
                key = plugin.get("key_source", "")
                if key and key in content:
                    required.append(pid)
                    print(f"  [plugin] {plugin['label']} required by: {f.name}")
    return required


def install_plugins(
    plugin_ids: List[str],
    unity_root: Path,
    dry_run: bool = False,
) -> dict:
    """
    Install listed plugins into the Unity project.

    Returns {"installed": [pid, ...], "failed": [pid, ...], "skipped": [pid, ...]}
    """
    result = {"installed": [], "failed": [], "skipped": []}

    if dry_run:
        for pid in plugin_ids:
            plugin = _PLUGINS.get(pid, {})
            print(f"  [dry-run] Would install: {plugin.get('label', pid)}")
        result["skipped"] = list(plugin_ids)
        return result

    for pid in plugin_ids:
        plugin = _PLUGINS.get(pid)
        if not plugin:
            print(f"  Unknown plugin: {pid}", file=sys.stderr)
            result["failed"].append(pid)
            continue

        success = plugin["install"](unity_root)
        if success:
            result["installed"].append(pid)
        else:
            result["skipped"].append(pid)

    return result


# =========================================================================
# CLI entry point
# =========================================================================

def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Auto-install Unity plugins needed by migrated Cocos scripts.",
        epilog="""\
Examples:
  # Detect from source and install
  python plugin_installer.py --unity ./MyUnity --src-dir ./MyGame/assets/scripts

  # Dry-run: show what would be installed
  python plugin_installer.py --unity ./MyUnity --src-dir ./MyGame/assets/scripts --dry-run
        """,
    )
    ap.add_argument("--unity", type=Path,
                    help="Unity project root (plugin .unitypackage copied here)")
    ap.add_argument("--src-dir", type=Path,
                    help="Cocos source scripts directory to scan for plugin needs")
    ap.add_argument("--plugin", action="append", default=[],
                    dest="plugins",
                    help="Force install a plugin ID (e.g. dotween). Use --plugin dotween")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be installed without copying files")
    ap.add_argument("--list", action="store_true",
                    help="List available plugins and exit")
    args = ap.parse_args()

    if args.list:
        print("Available plugins:")
        for pid, p in _PLUGINS.items():
            print(f"  {pid:12s}  {p['label']}")
        return 0

    if not args.unity:
        ap.error("--unity is required (or use --list to see available plugins)")

    # Collect plugin IDs to install
    to_install: List[str] = list(args.plugins)

    if args.src_dir:
        from_source = detect_from_source(args.src_dir)
        for pid in from_source:
            if pid not in to_install:
                to_install.append(pid)

    if not to_install:
        print("No plugins needed (or none detected).")
        return 0

    result = install_plugins(to_install, args.unity, dry_run=args.dry_run)

    print(f"\nDone. installed={len(result['installed'])}  "
          f"skipped={len(result['skipped'])}  failed={len(result['failed'])}")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
