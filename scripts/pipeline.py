#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pipeline.py
Unified entry point for the Cocos -> Unity migration pipeline.

Runs all 6 phases (0-5) in sequence using direct Python function calls —
no shell subprocess overhead. Each phase can also be run individually.

Usage:
  # Full pipeline (all phases)
  python pipeline.py \
    --cocos <cocos-root> \
    --unity <unity-root> \
    [--atlas] [--convert-pos] [--ppu 100] [--strict] [--dry-run]

  # Single phase
  python pipeline.py --cocos <cocos-root> --unity <unity-root> --phase 0
  python pipeline.py --cocos <cocos-root> --unity <unity-root> --phase 2  # 脚本
  python pipeline.py --cocos <cocos-root> --unity <unity-root> --phase 3  # 资产
  python pipeline.py --cocos <cocos-root> --unity <unity-root> --phase 4  # 预制体
  python pipeline.py --cocos <cocos-root> --unity <unity-root> --phase 5  # 关联
  python pipeline.py --cocos <cocos-root> --unity <unity-root> --phase 7 --strict  # 验证

Output directory structure:
  <unity-root>/
    Assets/_Ported/           # media assets + .meta
    Assets/_Ported/_Prefabs/  # converted prefabs (.prefab YAML)
    Assets/_Ported/_Scenes/   # converted scenes (.unity YAML)
    Assets/_Ported/Scripts/   # translated C# scripts
    Assets/_Ported/Animations/ # converted animation clips
    Assets/_Ported/Editor/    # widget helper scripts (optional)
  manifest.json               # asset UUID->GUID mapping
  report.json                 # Phase 0 audit report
  report.md                   # Phase 5 verification report
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure scripts/ is on the path for cross-module imports
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# SDK / ad content filter (shared module)
try:
    from sdk_filter import SdkFilter
except ImportError:
    SdkFilter = None


# =============================================================================
# Phase runners — each returns a result dict and prints progress
# =============================================================================

def phase_0_audit(cocos_root: Path, output_dir: Path, strip_sdk: bool = False, **_kwargs) -> Dict[str, Any]:
    """Phase 0: Project Audit (read-only)"""
    try:
        from audit_cocos_project import audit
        report = audit(cocos_root, strip_sdk=strip_sdk)
    except ImportError:
        print("  WARNING: audit_cocos_project.py not found, skipping audit")
        report = {
            "creator_generation": "unknown",
            "scenes": [],
            "script_stats": {"total_files": 0},
            "effort_estimate": "unknown",
            "spine_versions_detected": []
        }

    print("\n" + "=" * 60)
    print("PHASE 0 — Project Audit")
    if strip_sdk:
        print("  (--strip-sdk enabled: SDK/ad content will be flagged)")
    print("=" * 60)

    report_path = output_dir / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    gen = report.get("creator_generation", "unknown")
    scenes = len(report.get("scenes", []))
    scripts = report.get("script_stats", {}).get("total_files", 0)
    effort = report.get("effort_estimate", "?")
    spine = report.get("spine_versions_detected", [])

    print(f"  generation={gen}  scenes={scenes}  scripts={scripts}  effort={effort}")
    print(f"  report -> {report_path}")
    if spine:
        print(f"  spine versions: {', '.join(spine)}")

    return {"report_path": str(report_path), "report": report}


def phase_1_migrate(cocos_root: Path, unity_root: Path, output_dir: Path,
                    dry_run: bool = False, atlas: bool = False,
                    strip_sdk: bool = False, **_kwargs) -> Dict[str, Any]:
    """Phase 1: Resource Migration (media assets)"""
    from migrate_assets import migrate

    print("\n" + "=" * 60)
    print("PHASE 1 — Resource Migration")
    if strip_sdk:
        print("  (--strip-sdk enabled: SDK/ad assets will be skipped)")
    print("=" * 60)

    src = cocos_root / "assets"
    if not src.is_dir():
        src = cocos_root  # fallback

    dst = unity_root / "Assets" / "_Ported"

    if not dry_run:
        dst.mkdir(parents=True, exist_ok=True)

    manifest = migrate(src, dst, dry_run, atlas, strip_sdk=strip_sdk)

    manifest_path = output_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = manifest.get("stats", {})
    structural = stats.get("structural_skipped", {})
    structural_info = " ".join(f"{k}={v}" for k, v in structural.items()) if structural else "none"
    mode = "[DRY-RUN] " if dry_run else ""

    print(f"  {mode}copied={stats.get('copied', 0)}  skipped={stats.get('skipped', 0)}  "
          f"errors={stats.get('errors', 0)}  9slice={stats.get('has_9slice', 0)}  "
          f"atlases={stats.get('atlases_created', 0)}")
    if structural:
        print(f"  structural pending: {structural_info}")
    print(f"  manifest -> {manifest_path}")

    return {"manifest_path": str(manifest_path), "manifest": manifest}


def phase_2_convert(cocos_root: Path, unity_root: Path, manifest: Dict[str, Any],
                    ppu: float = 100, convert_pos: bool = False, **_kwargs) -> Dict[str, Any]:
    """Phase 2: Scene & Prefab Conversion (ALL structural assets)"""
    from convert_prefab import batch_convert, _scan_script_guids

    print("\n" + "=" * 60)
    print("PHASE 2 — Scene & Prefab Conversion")
    print("=" * 60)

    src = cocos_root / "assets"
    if not src.is_dir():
        src = cocos_root

    dst = unity_root / "Assets" / "_Ported"

    # 扫描脚本 GUID（在预制体转换前，确保 Phase 3 脚本已被迁移）
    _scan_script_guids(unity_root / "Assets")

    summary = batch_convert(src, dst, manifest, ppu, convert_pos)

    print(f"\n  prefabs={summary.get('prefabs', 0)}  scenes={summary.get('scenes', 0)}  "
          f"errors={summary.get('total_errors', 0)}")

    return {"summary": summary}


def phase_3_scripts(cocos_root: Path, unity_root: Path,
                    strip_sdk: bool = False, no_stub: bool = False, **_kwargs) -> Dict[str, Any]:
    """Phase 3: Script Translation (TS/JS -> C#) via LLM AI.

    Args:
        no_stub: 如果为 True，无 LLM 时跳过脚本生成而不是生成 stub
    """
    from translator import translate_path

    print("\n" + "=" * 60)
    print("PHASE 3 — Script Translation (AI-powered, TS/JS -> C#)")
    print("  Provider: auto-detected from env (OPENAI_API_KEY / ANTHROPIC_API_KEY)")
    if strip_sdk:
        print("  (--strip-sdk enabled: SDK scripts will be stubbed)")
    if no_stub:
        print("  (--no-stub enabled: 无 LLM 时跳过脚本生成)")
    print("=" * 60)

    sdk_filt = SdkFilter() if (strip_sdk and SdkFilter) else None

    # 记录未映射脚本
    script_mapping: dict = {}

    # Look for scripts directory
    src_candidates = [
        cocos_root / "assets" / "scripts",
        cocos_root / "assets" / "Scripts",
        cocos_root / "assets" / "script",
        cocos_root / "assets" / "Script",
        cocos_root / "assets",
    ]
    src_dir = None
    for candidate in src_candidates:
        if candidate.is_dir():
            has_scripts = any(candidate.rglob("*.ts")) or any(candidate.rglob("*.js"))
            if has_scripts:
                src_dir = candidate
                break

    if src_dir is None:
        print("  No script files found. Skipping Phase 3.")
        return {"total": 0, "notes": 0, "skipped": 0}

    out_dir = unity_root / "Assets" / "_Ported" / "Scripts"
    total = 0
    total_notes = 0
    sdk_stubs = 0
    skipped = 0

    for ext_pattern in ("*.ts", "*.js"):
        for src_file in src_dir.rglob(ext_pattern):
            if src_file.name.endswith(".d.ts"):
                continue
            rel = src_file.relative_to(src_dir).with_suffix(".cs")
            try:
                notes = translate_path(src_file, out_dir / rel, sdk_filter=sdk_filt,
                                      no_stub=no_stub, script_mapping=script_mapping)
                if notes and "skipped" in notes[0].lower():
                    skipped += 1
                    print(f"  [SKIP] {src_file.name} -> {rel} ({notes[0]})")
                else:
                    total += 1
                    total_notes += len(notes)
                    is_stub = any("STUB:" in n for n in notes)
                    if is_stub:
                        sdk_stubs += 1
                    print(f"  {'[STUB] ' if is_stub else ''}{src_file.name} -> {rel} ({len(notes)} notes)")
            except Exception as e:
                print(f"  ERROR {src_file.name}: {e}", file=sys.stderr)

    print(f"\n  translated={total}  skipped={skipped}  total_notes={total_notes}")
    if sdk_stubs:
        print(f"  SDK/ad stubs generated: {sdk_stubs}")

    # 输出未映射脚本列表
    if script_mapping:
        unmapped_file = unity_root / "Assets" / "_Ported" / "unmapped_scripts.json"
        unmapped_file.parent.mkdir(parents=True, exist_ok=True)
        with open(unmapped_file, 'w', encoding='utf-8') as f:
            json.dump(script_mapping, f, indent=2, ensure_ascii=False)
        print(f"  Saved unmapped scripts to: {unmapped_file}")

    # --- Auto-install plugins based on detected source features ---
    from plugin_installer import detect_from_source, install_plugins
    needed = detect_from_source(src_dir)
    if needed:
        install_plugins(needed, unity_root)

    return {"total": total, "notes": total_notes, "sdk_stubs": sdk_stubs, "skipped": skipped}


def phase_35_link_scripts(cocos_root: Path, unity_root: Path, **_kwargs) -> Dict[str, Any]:
    """Phase 3.5: Link translated C# scripts to prefabs/scenes"""
    from link_scripts import build_cocos_to_guid_map, fix_prefab_refs, fix_scene_refs

    print("\n" + "=" * 60)
    print("PHASE 3.5 — Link Scripts to Prefabs/Scenes")
    print("=" * 60)

    # 建立 Cocos UUID → Unity GUID 映射
    cocos_to_guid, uuid_to_name = build_cocos_to_guid_map(cocos_root, unity_root)
    print(f"  Found {len(cocos_to_guid)} script mappings")

    # 修复预制体
    total_fixed = 0
    total_skipped = 0
    total_failed = 0
    ported_dir = unity_root / "Assets" / "_Ported"

    print("\n  Fixing prefabs...")
    for prefab in ported_dir.rglob("*.prefab"):
        fixed, skipped, failed = fix_prefab_refs(prefab, cocos_to_guid, uuid_to_name, unity_root, dry_run=False)
        total_fixed += fixed
        total_skipped += skipped
        total_failed += failed

    print("\n  Fixing scenes...")
    for scene in ported_dir.rglob("*.unity"):
        fixed, skipped, failed = fix_scene_refs(scene, cocos_to_guid, uuid_to_name, unity_root, dry_run=False)
        total_fixed += fixed
        total_skipped += skipped
        total_failed += failed

    print(f"\n  Summary: {total_fixed} refs fixed, {total_skipped} skipped, {total_failed} failed")

    return {"fixed": total_fixed, "skipped": total_skipped, "failed": total_failed}


def phase_4_anim(cocos_root: Path, unity_root: Path, **_kwargs) -> Dict[str, Any]:
    """Phase 4: Animation / Spine / Audio / UI Polish"""
    from convert_anim import batch_convert as anim_batch_convert

    print("\n" + "=" * 60)
    print("PHASE 4 — Animation Conversion")
    print("=" * 60)

    src = cocos_root / "assets"
    if not src.is_dir():
        src = cocos_root

    dst = unity_root / "Assets" / "_Ported" / "Animations"
    summary = anim_batch_convert(src, dst)

    total = summary.get("total_converted", 0)
    errors_count = summary.get("total_errors", 0)

    if total == 0:
        print("  No .anim files found. Skipping.")
    else:
        print(f"\n  converted={total}  errors={errors_count}")

    print("\n  Note: Spine/DragonBones/Audio/UI need manual attention.")
    print("  See SKILL.md Phase 4 for details.")

    return summary


def phase_5_verify(unity_root: Path, output_dir: Path, manifest_path: Path,
                   strict: bool = False, **_kwargs) -> Dict[str, Any]:
    """Phase 5: Verification & Cleanup"""
    # Import verify_migration's main() is monolithic, so we replicate logic here
    # or run it via its module. Since verify has no standalone function, we call main()
    # via sys.argv manipulation (cleaner than copy-pasting 200 lines).
    print("\n" + "=" * 60)
    print("PHASE 5 — Verification & Cleanup")
    print("=" * 60)

    report_path = output_dir / "report.md"

    # Build argv for verify_migration.main()
    saved_argv = sys.argv
    sys.argv = [
        "verify_migration.py",
        "--unity", str(unity_root),
        "--manifest", str(manifest_path),
        "--report", str(report_path),
    ]
    if strict:
        sys.argv.append("--strict")

    try:
        from verify_migration import main as verify_main
        exit_code = verify_main()
    finally:
        sys.argv = saved_argv

    return {"report_path": str(report_path), "exit_code": exit_code}


# =============================================================================
# Pipeline orchestrator
# =============================================================================

def run_pipeline(args: argparse.Namespace) -> int:
    """Run the full pipeline or a single phase."""
    cocos_root = Path(args.cocos).resolve()
    unity_root = Path(args.unity).resolve()
    output_dir = Path(args.output) if args.output else unity_root

    if not cocos_root.is_dir():
        print(f"ERROR: Cocos project root not found: {cocos_root}", file=sys.stderr)
        return 2

    phases_to_run: List[int] = []
    if args.phase is not None:
        phases_to_run = [args.phase]
    else:
        # 执行顺序：Phase 2 脚本先于 Phase 3 资产，确保 .meta 文件在预制体转换前生成
        phases_to_run = [0, 2, 3, 4, 5, 6, 7]

    start = time.time()
    manifest: Optional[Dict[str, Any]] = None
    manifest_path: Optional[Path] = None

    # Load existing manifest if only running later phases
    if phases_to_run[0] > 1:
        mp = output_dir / "manifest.json"
        if mp.is_file():
            manifest = json.loads(mp.read_text(encoding="utf-8"))
            manifest_path = mp
            print(f"Loaded existing manifest: {mp}")
        else:
            print(f"WARNING: No manifest found at {mp}. Phase 2+ may fail.", file=sys.stderr)

    print(f"Cocos project: {cocos_root}")
    print(f"Unity project: {unity_root}")
    print(f"Output dir:    {output_dir}")
    print(f"Phases to run: {phases_to_run}")
    if args.strip_sdk:
        print(f"Strip SDK/ad:  ENABLED")

    results: Dict[int, Any] = {}
    exit_code = 0

    for phase in phases_to_run:
        phase_start = time.time()

        try:
            if phase == 0:
                result = phase_0_audit(cocos_root, output_dir,
                                       strip_sdk=args.strip_sdk)
                results[0] = result

            elif phase == 2:
                # Phase 2: 脚本翻译
                result = phase_3_scripts(cocos_root, unity_root,
                                         strip_sdk=args.strip_sdk,
                                         no_stub=args.no_stub)
                results[2] = result

            elif phase == 3:
                # Phase 3: 资产迁移
                result = phase_1_migrate(
                    cocos_root, unity_root, output_dir,
                    dry_run=args.dry_run, atlas=args.atlas,
                    strip_sdk=args.strip_sdk,
                )
                manifest = result["manifest"]
                manifest_path = Path(result["manifest_path"])
                results[3] = result

            elif phase == 4:
                # Phase 4: 预制体转换
                if manifest is None:
                    print("ERROR: Phase 4 requires manifest. Run Phase 3 first.", file=sys.stderr)
                    return 2
                result = phase_2_convert(
                    cocos_root, unity_root, manifest,
                    ppu=args.ppu, convert_pos=args.convert_pos
                )
                results[4] = result

            elif phase == 5:
                # Phase 5: 脚本关联
                result = phase_35_link_scripts(cocos_root, unity_root)
                results[5] = result

            elif phase == 6:
                # Phase 6: 动画转换
                result = phase_4_anim(cocos_root, unity_root)
                results[6] = result

            elif phase == 7:
                # Phase 7: 验证
                if manifest_path is None:
                    mp = output_dir / "manifest.json"
                    if mp.is_file():
                        manifest_path = mp
                    else:
                        print("ERROR: Phase 7 requires manifest. Run Phase 3 first.", file=sys.stderr)
                        return 2
                result = phase_5_verify(
                    unity_root, output_dir, manifest_path,
                    strict=args.strict
                )
                results[7] = result
                if result.get("exit_code", 0) != 0:
                    exit_code = 1

        except Exception as e:
            print(f"\n  FATAL ERROR in Phase {phase}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

        elapsed = time.time() - phase_start
        print(f"\n  Phase {phase} completed in {elapsed:.1f}s")

    total_elapsed = time.time() - start

    # Final summary
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Total time: {total_elapsed:.1f}s")
    print(f"  Phases run: {phases_to_run}")

    if 0 in results:
        r = results[0].get("report", {})
        print(f"  Audit: generation={r.get('creator_generation', '?')} "
              f"effort={r.get('effort_estimate', '?')}")
    if 1 in results:
        stats = results[1].get("manifest", {}).get("stats", {})
        print(f"  Migration: copied={stats.get('copied', 0)} errors={stats.get('errors', 0)}")
    if 2 in results:
        s = results[2].get("summary", {})
        print(f"  Conversion: prefabs={s.get('prefabs', 0)} scenes={s.get('scenes', 0)} "
              f"errors={s.get('total_errors', 0)}")
    if 3 in results:
        print(f"  Scripts: translated={results[3].get('total', 0)}")
    if 4 in results:
        print(f"  Animations: converted={results[4].get('total', 0)}")
    if 5 in results:
        print(f"  Verify: report -> {results[5].get('report_path', '?')}")

    return exit_code


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cocos -> Unity Migration Pipeline (unified Python entry point)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline
  python pipeline.py --cocos ./MyGame --unity ./MyUnityProject

  # Audit only (Phase 0)
  python pipeline.py --cocos ./MyGame --unity ./MyUnityProject --phase 0

  # Migrate assets and convert prefabs (Phase 1+2)
  python pipeline.py --cocos ./MyGame --unity ./MyUnityProject --phase 1
  python pipeline.py --cocos ./MyGame --unity ./MyUnityProject --phase 2

  # Full pipeline with atlas and position conversion
  python pipeline.py --cocos ./MyGame --unity ./MyUnityProject --atlas --convert-pos --ppu 100
        """,
    )
    ap.add_argument("--cocos", required=True, help="Cocos Creator project root")
    ap.add_argument("--unity", required=True, help="Unity project root")
    ap.add_argument("--output", help="Output directory for reports/manifest (default: unity root)")
    ap.add_argument("--phase", type=int, choices=[0, 2, 3, 4, 5, 6, 7],
                    help="Run only this phase (default: all)")
    ap.add_argument("--ppu", type=float, default=100,
                    help="Pixels per unit (default: 100)")
    ap.add_argument("--convert-pos", action="store_true",
                    help="Divide positions by PPU for Unity world units")
    ap.add_argument("--atlas", action="store_true",
                    help="Generate SpriteAtlas per top-level folder (Phase 1)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview Phase 1 without copying files")
    ap.add_argument("--strict", action="store_true",
                    help="Phase 5: treat warnings as errors (exit code 1)")
    ap.add_argument("--strip-sdk", action="store_true",
                    help="Exclude SDK/ad/analytics/social content from migration "
                         "(assets skipped, scripts stubbed, broken refs fixed)")
    ap.add_argument("--no-stub", action="store_true", default=False,
                    help="无 LLM 时跳过脚本生成（不生成 stub），保留引用到 unmapped_scripts.json")
    ap.add_argument("--generate-stub", action="store_true",
                    help="无 LLM 时生成 stub 脚本（用于保留脚本引用）")
    ap.add_argument("--target", action="append", default=None,
                    help="Selective migration: only migrate this scene/prefab and "
                         "its dependencies. Can be specified multiple times. "
                         "When set, runs selective_migrate instead of full pipeline.")

    args = ap.parse_args()

    # --generate-stub 覆盖 --no-stub
    if args.generate_stub:
        args.no_stub = False

    # Ensure utf-8 output on Windows (for Chinese path names etc.)
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # If --target is used, delegate to selective_migrate
    if args.target:
        from selective_migrate import selective_migrate
        result = selective_migrate(
            cocos_root=Path(args.cocos).resolve(),
            unity_root=Path(args.unity).resolve(),
            targets=args.target,
            ppu=args.ppu,
            convert_pos=args.convert_pos,
            dry_run=args.dry_run,
            strip_sdk=args.strip_sdk,
            output_dir=Path(args.output) if args.output else None,
        )
        return 2 if result.get("error") else 0

    return run_pipeline(args)


if __name__ == "__main__":
    sys.exit(main())
