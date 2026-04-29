#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
link_scripts.py — 将预制体/场景中的脚本引用与实际 C# 脚本关联

核心问题：
- Cocos Creator 使用 UUID 编码（如 08b27n+8j1F2I3d12RZuHk0）作为组件类型标识符
- 实际脚本名称（如 CupComp）在 library/imports 目录中定义
- Unity 需要 GUID 来关联脚本

解决方案：
1. 从 library/imports 目录扫描建立 UUID编码 → 脚本名 映射
2. 扫描所有 C# 脚本的 .meta 获取脚本名 → GUID 映射
3. 关联预制体中的占位符为正确的 GUID
4. 无法映射的脚本名记录到 unmapped_scripts.json，待 Unity 生成脚本后查找
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ============================================================================
# 全局：未映射的脚本名集合
# ============================================================================
_unmapped_scripts: Set[str] = set()


def load_imports_mapping(cocos_root: Path) -> Dict[str, str]:
    """从 library/imports 扫描建立 UUID编码 → 脚本名 映射"""
    uuid_to_name: Dict[str, str] = {}
    imports_dir = cocos_root / "library" / "imports"

    if not imports_dir.exists():
        print(f"  Warning: {imports_dir} not found")
        return uuid_to_name

    # 扫描所有 .js 文件
    for js_file in imports_dir.rglob("*.js"):
        try:
            content = js_file.read_text(encoding="utf-8", errors="ignore")
            # 匹配 cc._RF.push(module, 'UUID', 'ClassName');
            match = re.search(r"cc\._RF\.push\([^)]+,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", content)
            if match:
                uuid_encoded = match.group(1)
                class_name = match.group(2)
                uuid_to_name[uuid_encoded] = class_name
        except Exception:
            pass

    return uuid_to_name


def load_uuid_mtime_mapping(cocos_root: Path) -> Dict[str, str]:
    """从 uuid-to-mtime.json 加载 UUID → 文件名 映射"""
    uuid_to_filename: Dict[str, str] = {}
    uuid_meta = cocos_root / "library" / "uuid-to-mtime.json"

    if not uuid_meta.exists():
        return uuid_to_filename

    try:
        with open(uuid_meta, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for uuid_val, info in data.items():
            rel_path = info.get("relativePath", "")
            if rel_path and ('.js' in rel_path or '.ts' in rel_path):
                filename = Path(rel_path).stem
                # 存储无连字符版本
                uuid_key = uuid_val.replace("-", "")
                uuid_to_filename[uuid_key] = filename
    except Exception as e:
        print(f"  Warning: Failed to load uuid-to-mtime.json: {e}")

    return uuid_to_filename


def scan_csharp_guid_map(unity_root: Path) -> Dict[str, str]:
    """扫描 Unity 项目中所有 C# 脚本，获取脚本名 → GUID 映射"""
    guid_map: Dict[str, str] = {}

    for meta_file in unity_root.rglob("*.cs.meta"):
        # 跳过 Library 目录
        if "Library" in meta_file.parts:
            continue
        try:
            content = meta_file.read_text(encoding="utf-8")
            guid_match = re.search(r'^guid:\s*([a-f0-9]+)', content, re.MULTILINE)
            if guid_match:
                guid = guid_match.group(1)
                # .cs.meta 的 stem 是 "XXX.cs"，需要再切一次
                raw_stem = meta_file.stem
                if raw_stem.endswith(".cs"):
                    class_name = raw_stem[:-3]  # 去掉 ".cs"
                else:
                    class_name = raw_stem
                guid_map[class_name] = guid
        except Exception:
            pass

    return guid_map


def build_cocos_to_guid_map(cocos_root: Path, unity_root: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    """建立 Cocos UUID编码 → Unity GUID 的完整映射

    Returns:
        cocos_to_guid: Cocos UUID编码 → Unity GUID
        uuid_to_name: Cocos UUID编码 → 脚本名（用于记录未映射的）
    """
    # 1. 从 imports 目录获取 UUID编码 → 脚本名
    imports_map = load_imports_mapping(cocos_root)

    # 2. 从 uuid-to-mtime 获取无连字符UUID → 文件名
    uuid_mtime_map = load_uuid_mtime_mapping(cocos_root)

    # 3. 合并两个映射
    uuid_to_name: Dict[str, str] = {}
    uuid_to_name.update(imports_map)  # imports 有优先权（更准确）
    for uuid_enc, filename in uuid_mtime_map.items():
        if uuid_enc not in uuid_to_name:
            uuid_to_name[uuid_enc] = filename

    # 4. 脚本名 → GUID
    name_to_guid = scan_csharp_guid_map(unity_root)

    # 5. 合并：Cocos UUID编码 → GUID
    cocos_to_guid: Dict[str, str] = {}
    for uuid_enc, name in uuid_to_name.items():
        if name in name_to_guid:
            cocos_to_guid[uuid_enc] = name_to_guid[name]

    return cocos_to_guid, uuid_to_name


def load_unmapped_scripts(unity_root: Path) -> Dict[str, List[str]]:
    """加载已记录的未映射脚本列表"""
    unmapped_file = unity_root / "_Ported" / "unmapped_scripts.json"
    if unmapped_file.exists():
        try:
            with open(unmapped_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_unmapped_scripts(unity_root: Path, unmapped_data: Dict[str, List[str]]):
    """保存未映射的脚本列表到 JSON"""
    unmapped_file = unity_root / "_Ported" / "unmapped_scripts.json"
    unmapped_file.parent.mkdir(parents=True, exist_ok=True)

    with open(unmapped_file, 'w', encoding='utf-8') as f:
        json.dump(unmapped_data, f, indent=2, ensure_ascii=False)
    print(f"  Saved unmapped scripts to: {unmapped_file}")


def fix_prefab_refs(prefab_path: Path, cocos_to_guid: Dict[str, str],
                    uuid_to_name: Dict[str, str],
                    unity_root: Path, dry_run: bool = True) -> Tuple[int, int, int]:
    """修复预制体中的脚本引用，返回 (成功数, 跳过数, 失败数)"""
    global _unmapped_scripts
    fixed = 0
    skipped = 0
    failed = 0
    file_unmapped: List[str] = []

    # 构建脚本名 -> GUID 映射（用于脚本名格式的 TODO）
    # 延迟加载，只在第一次调用时构建
    if not hasattr(fix_prefab_refs, '_name_to_guid_cache'):
        fix_prefab_refs._name_to_guid_cache = scan_csharp_guid_map(unity_root)

    name_to_guid = fix_prefab_refs._name_to_guid_cache

    try:
        content = prefab_path.read_text(encoding="utf-8", errors="ignore")
        original_content = content

        lines = content.split('\n')
        new_lines = []

        # TODO 在 m_Script 行之后，先收集所有 TODO 映射
        # {m_Script_line_index: (cocos_uuid_or_name, script_name)}
        script_to_info: Dict[int, Tuple[str, str]] = {}
        for i, line in enumerate(lines):
            # 格式1: Cocos UUID 格式（如 426e5PHm2BHR78k6LhxQnQk.cs）
            # 格式2: 脚本名格式（如 ClickPopup.cs script reference）
            match = re.search(r'# TODO\(cocos2unity\):\s*Assign\s+([a-zA-Z0-9+/]+)\.cs(?:\s+script\s+reference)?', line)
            if match:
                cocos_id = match.group(1)
                # 优先尝试 UUID -> 名称映射
                script_name = uuid_to_name.get(cocos_id, cocos_id)
                # 向前找 m_Script: {fileID: 0}
                for j in range(i-1, max(0, i-5)-1, -1):
                    if re.match(r'\s*m_Script:\s*\{\s*fileID:\s*0\s*\}', lines[j]):
                        script_to_info[j] = (cocos_id, script_name)
                        break

        # 处理每一行
        for i, line in enumerate(lines):
            if re.match(r'\s*m_Script:\s*\{\s*fileID:\s*0\s*\}', line):
                info = script_to_info.get(i)
                if info:
                    cocos_id, script_name = info
                    guid = None
                    
                    # 策略1: 优先通过 Cocos UUID 直接查找
                    if cocos_id in cocos_to_guid:
                        guid = cocos_to_guid[cocos_id]
                    
                    # 策略2: 如果没找到，尝试通过脚本名查找
                    if guid is None:
                        # 在 uuid_to_name 的值中找到脚本名对应的 Cocos UUID
                        if cocos_id in uuid_to_name.values():
                            for cocos_key, name_val in uuid_to_name.items():
                                if name_val == cocos_id and cocos_key in cocos_to_guid:
                                    guid = cocos_to_guid[cocos_key]
                                    break
                    
                    # 策略3: 直接用脚本名作为 key（脚本名格式的 TODO）
                    if guid is None and cocos_id in name_to_guid:
                        guid = name_to_guid[cocos_id]
                    
                    # 策略4: 尝试小写脚本名
                    if guid is None:
                        for name, g in name_to_guid.items():
                            if name.lower() == cocos_id.lower():
                                guid = g
                                break
                    
                    if guid:
                        new_lines.append(line.replace('{fileID: 0}', f'{{fileID: 11500000, guid: {guid}, type: 3}}'))
                        fixed += 1
                    else:
                        # 无法映射：记录脚本名
                        _unmapped_scripts.add(script_name)
                        file_unmapped.append(script_name)
                        failed += 1
                        new_lines.append(line)
                else:
                    # 没有 TODO 注释的 m_Script: {fileID: 0}
                    skipped += 1
                    new_lines.append(line)
            else:
                new_lines.append(line)

        new_content = '\n'.join(new_lines)

        if not dry_run and new_content != original_content:
            prefab_path.write_text(new_content, encoding="utf-8")
            print(f"  Fixed: {prefab_path.relative_to(unity_root)} ({fixed} refs)")

        # 报告此文件的未映射脚本
        if file_unmapped:
            print(f"  [Unmapped in {prefab_path.name}]: {', '.join(file_unmapped)}")

        return fixed, skipped, failed

    except Exception as e:
        print(f"  Error: {prefab_path.name}: {e}")
        return 0, 0, 1


def fix_scene_refs(scene_path: Path, cocos_to_guid: Dict[str, str],
                   uuid_to_name: Dict[str, str],
                   unity_root: Path, dry_run: bool = True) -> Tuple[int, int, int]:
    """修复场景中的脚本引用"""
    return fix_prefab_refs(scene_path, cocos_to_guid, uuid_to_name, unity_root, dry_run)


def resolve_unmapped_scripts(unity_root: Path) -> Tuple[int, int]:
    """尝试解析之前未映射的脚本

    扫描 Unity 项目中新增的 C# 脚本，查找之前未映射的脚本名。

    Returns:
        (resolved_count, remaining_count)
    """
    global _unmapped_scripts

    if not _unmapped_scripts:
        print("  No unmapped scripts to resolve")
        return 0, 0

    print(f"\n[Resolve] Trying to resolve {len(_unmapped_scripts)} unmapped scripts...")

    # 扫描 Unity 中的 C# 脚本
    name_to_guid = scan_csharp_guid_map(unity_root)

    resolved = 0
    still_unmapped: Set[str] = set()

    for script_name in _unmapped_scripts:
        # 尝试精确匹配
        if script_name in name_to_guid:
            print(f"  Resolved: {script_name} -> {name_to_guid[script_name]}")
            resolved += 1
        else:
            # 尝试模糊匹配（去掉特殊字符后匹配）
            sanitized = re.sub(r'[^a-zA-Z0-9]', '', script_name)
            for cs_name, guid in name_to_guid.items():
                if re.sub(r'[^a-zA-Z0-9]', '', cs_name) == sanitized:
                    print(f"  Resolved (fuzzy): {script_name} -> {cs_name} -> {guid}")
                    resolved += 1
                    break
            else:
                still_unmapped.add(script_name)

    print(f"  Resolved: {resolved}, Remaining: {len(still_unmapped)}")
    _unmapped_scripts = still_unmapped

    return resolved, len(still_unmapped)


def main() -> int:
    ap = argparse.ArgumentParser(description="关联预制体/场景与 C# 脚本")
    ap.add_argument("--cocos", required=True, help="Cocos Creator 项目根目录")
    ap.add_argument("--unity", required=True, help="Unity 项目根目录")
    ap.add_argument("--dry-run", action="store_true", help="仅显示将要修复的内容，不实际修改")
    ap.add_argument("--resolve", action="store_true", help="尝试解析之前未映射的脚本")
    ap.add_argument("--clear-unmapped", action="store_true", help="清除未映射脚本记录")
    args = ap.parse_args()

    global _unmapped_scripts
    cocos_root = Path(args.cocos)
    unity_root = Path(args.unity)
    dry_run = args.dry_run

    # 加载之前记录的未映射脚本
    unmapped_data = load_unmapped_scripts(unity_root)
    if unmapped_data:
        print(f"\n[Loaded] Previous unmapped scripts from other files:")
        for file_path, scripts in unmapped_data.items():
            print(f"  {file_path}: {scripts}")

    # 1. 建立 Cocos UUID编码 → Unity GUID 映射
    print("\n[1/5] Building Cocos UUID → C# Script → Unity GUID mapping...")
    cocos_to_guid, uuid_to_name = build_cocos_to_guid_map(cocos_root, unity_root)
    print(f"  Found {len(cocos_to_guid)} Cocos scripts with GUID mappings")
    print(f"  Total UUID entries: {len(uuid_to_name)}")

    if cocos_to_guid:
        print("  Sample mappings:")
        for cocos_uuid, guid in list(cocos_to_guid.items())[:5]:
            script_name = uuid_to_name.get(cocos_uuid, "?")
            print(f"    {cocos_uuid[:20]}... -> {script_name} -> {guid}")
    else:
        print("  Warning: No mappings found!")
        print("  This may mean:")
        print("    1. Phase 3 scripts haven't been generated yet")
        print("    2. C# scripts don't have .meta files with GUIDs")

    # 2. 如果指定 --resolve，尝试解析之前未映射的脚本
    if args.resolve:
        # 将之前记录的未映射脚本加入全局集合
        for scripts in unmapped_data.values():
            _unmapped_scripts.update(scripts)

        resolved, remaining = resolve_unmapped_scripts(unity_root)
        if remaining == 0:
            print("\n  All unmapped scripts resolved! You can now run without --resolve")
            # 清除记录
            (unity_root / "_Ported" / "unmapped_scripts.json").unlink(missing_ok=True)
            return 0

    # 3. 扫描预制体
    print("\n[2/5] Scanning prefabs...")
    ported_dir = unity_root / "Assets" / "_Ported"
    prefab_files = list(ported_dir.rglob("*.prefab"))

    total_fixed = 0
    total_skipped = 0
    total_failed = 0
    all_unmapped: Dict[str, List[str]] = {}

    for prefab in prefab_files:
        fixed, skipped, failed = fix_prefab_refs(prefab, cocos_to_guid, uuid_to_name, unity_root, dry_run)
        total_fixed += fixed
        total_skipped += skipped
        total_failed += failed

        # 收集此文件的未映射脚本
        if failed > 0:
            # 重新解析以获取文件名
            content = prefab.read_text(encoding="utf-8", errors="ignore")
            lines = content.split('\n')
            file_scripts: List[str] = []
            for i, line in enumerate(lines):
                match = re.search(r'# TODO\(cocos2unity\):\s*Assign\s+([a-zA-Z0-9+]+)\.cs', line)
                if match:
                    cocos_uuid = match.group(1)
                    if cocos_uuid not in cocos_to_guid:
                        script_name = uuid_to_name.get(cocos_uuid, cocos_uuid)
                        if script_name not in file_scripts:
                            file_scripts.append(script_name)
            if file_scripts:
                rel_path = str(prefab.relative_to(ported_dir))
                all_unmapped[rel_path] = file_scripts

    print(f"  Prefabs: {len(prefab_files)} files")
    print(f"    Fixed: {total_fixed}, Skipped: {total_skipped}, Failed: {total_failed}")

    # 4. 扫描场景
    print("\n[3/5] Scanning scenes...")
    scene_files = list(ported_dir.rglob("*.unity"))

    for scene in scene_files:
        fixed, skipped, failed = fix_scene_refs(scene, cocos_to_guid, uuid_to_name, unity_root, dry_run)
        total_fixed += fixed
        total_skipped += skipped
        total_failed += failed

        # 收集此文件的未映射脚本
        if failed > 0:
            content = scene.read_text(encoding="utf-8", errors="ignore")
            lines = content.split('\n')
            file_scripts: List[str] = []
            for i, line in enumerate(lines):
                match = re.search(r'# TODO\(cocos2unity\):\s*Assign\s+([a-zA-Z0-9+]+)\.cs', line)
                if match:
                    cocos_uuid = match.group(1)
                    if cocos_uuid not in cocos_to_guid:
                        script_name = uuid_to_name.get(cocos_uuid, cocos_uuid)
                        if script_name not in file_scripts:
                            file_scripts.append(script_name)
            if file_scripts:
                rel_path = str(scene.relative_to(ported_dir))
                all_unmapped[rel_path] = file_scripts

    print(f"  Scenes: {len(scene_files)} files")

    # 5. 保存未映射的脚本
    print("\n[4/5] Saving unmapped scripts...")
    if all_unmapped:
        save_unmapped_scripts(unity_root, all_unmapped)
        print(f"  Total unmapped scripts: {sum(len(v) for v in all_unmapped.values())}")
        print("  These scripts will be auto-resolved when you add them to Unity")
    else:
        # 清除记录
        unmapped_file = unity_root / "_Ported" / "unmapped_scripts.json"
        if unmapped_file.exists():
            unmapped_file.unlink()
            print("  Cleared unmapped scripts record")

    # 6. 总结
    print("\n" + "=" * 60)
    print(f"Total: {total_fixed} refs fixed, {total_skipped} skipped, {total_failed} failed")

    if dry_run:
        print("\n[Dry run mode - no files were modified]")
        print("Remove --dry-run to apply changes")

    if total_failed > 0:
        print(f"\n[Action Required] {total_failed} scripts could not be mapped.")
        print("  1. Run Phase 3 (translator) to generate C# scripts")
        print("  2. Run: python scripts/link_scripts.py --cocos <path> --unity <path> --resolve")
        print("     This will find newly created scripts and auto-link them")

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
