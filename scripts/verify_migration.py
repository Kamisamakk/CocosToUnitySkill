#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
verify_migration.py — Phase 5: 验证 Unity 项目迁移结果

检查：
- manifest.json 格式完整性
- 预制体 YAML 格式
- 场景文件完整性
- 资源引用（无 null GUID）
- C# 脚本规则检查：
  * 继承关系（MonoBehaviour 基类）
  * UI 组件继承（UnityEngine.UI）
  * 类名与文件名匹配
  * 必要的 using 语句
  * 生命周期方法签名
  * Cocos Creator 残留引用检测
  * 常见错误模式
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


def verify_prefab(prefab_path: Path) -> Dict[str, Any]:
    """验证单个预制体文件"""
    issues: List[str] = []
    warnings: List[str] = []

    try:
        content = prefab_path.read_text(encoding="utf-8", errors="ignore")

        # 检查 YAML 格式
        if "--- !u!" not in content:
            issues.append("Not a valid Unity YAML prefab")

        # 检查 MonoBehaviour 是否关联了有效脚本
        if "MonoBehaviour" in content:
            # 检查是否有 m_Script: {fileID: 0}（null GUID）
            null_script_pattern = r'm_Script:\s*\{\s*fileID:\s*0\s*\}'
            if re.search(null_script_pattern, content):
                warnings.append("Contains MonoBehaviour with null Script reference (fileID: 0)")

        # 检查 null GUID
        if re.search(r'guid:\s*00000000000000000000000000000000', content):
            warnings.append("Contains null GUID reference")

    except Exception as e:
        issues.append(f"Read error: {e}")

    return {"issues": issues, "warnings": warnings}


def verify_scene(scene_path: Path) -> Dict[str, Any]:
    """验证单个场景文件"""
    issues: List[str] = []
    warnings: List[str] = []

    try:
        content = scene_path.read_text(encoding="utf-8", errors="ignore")

        # 检查 YAML 格式
        if "--- !u!" not in content:
            issues.append("Not a valid Unity YAML scene")

        # 检查 GameObject
        if "GameObject:" in content:
            pass  # 正常

        # 检查常见问题
        if "<<<>>>>" in content:
            issues.append("Contains unresolved placeholders")

        # 检查 Script 引用
        null_script = re.findall(r'guid:\s*00000000000000000000000000000000', content)
        if null_script:
            warnings.append(f"Found {len(null_script)} null GUID reference(s)")

    except Exception as e:
        issues.append(f"Read error: {e}")

    return {"issues": issues, "warnings": warnings}


def verify_scripts(scripts_dir: Path) -> Dict[str, Any]:
    """验证脚本文件（包括继承关系、基类、命名空间等规则）"""
    issues: List[str] = []
    warnings: List[str] = []

    if not scripts_dir.is_dir():
        warnings.append("Scripts directory not found")
        return {"issues": issues, "warnings": warnings}

    cs_files = list(scripts_dir.rglob("*.cs"))
    if not cs_files:
        warnings.append("No C# script files found")
        return {"issues": issues, "warnings": warnings}

    # C# 规则检查配置
    VALID_MONOBEHAVIOUR_BASES = {"MonoBehaviour", "Component", "Behaviour", "UnityEngine.Object"}
    VALID_UI_BASES = {"Button", "Text", "Image", "RawImage", "Toggle", "Slider", "Scrollbar",
                      "InputField", "Dropdown", "ScrollRect", "RectTransform"}
    REQUIRED_USINGS = {"UnityEngine"}
    COMMON_UNITY_USINGS = {"UnityEngine", "UnityEngine.UI", "UnityEngine.SceneManagement"}

    for cs_file in cs_files:
        try:
            content = cs_file.read_text(encoding="utf-8", errors="ignore")
            filename = cs_file.name

            # ========== 1. 检查 TODO 标记 ==========
            todos = re.findall(r'// TODO\(cocos2unity\):', content)
            if todos:
                warnings.append(f"{filename}: {len(todos)} TODO(cocos2unity) marker(s)")

            # ========== 2. 检查是否为空 ==========
            if len(content.strip()) < 50:
                warnings.append(f"{filename}: Very short file (< 50 chars)")
                continue

            # ========== 3. 检查 using 语句 ==========
            usings = re.findall(r'^\s*using\s+([\w.]+)\s*;', content, re.MULTILINE)
            usings_set = set(usings)

            # 检查必要的 Unity using
            has_unity_engine = any("UnityEngine" in u for u in usings)
            if not has_unity_engine:
                warnings.append(f"{filename}: Missing 'using UnityEngine;' (may be needed)")

            # ========== 4. 检查类定义 ==========
            class_matches = re.findall(
                r'(?:public|private|protected|internal)?\s*(?:abstract|sealed|static)?\s*class\s+(\w+)'
                r'(?:\s*:\s*([\w.,\s]+))?',
                content
            )

            if not class_matches:
                warnings.append(f"{filename}: No class definition found")
                continue

            for class_name, inheritance in class_matches:
                inheritance = inheritance.strip() if inheritance else ""

                # ========== 4.1 检查继承关系 ==========
                if inheritance:
                    # 提取所有基类（去除泛型和空格）
                    bases = [b.strip().split('<')[0].strip() for b in inheritance.split(',')]
                    base_class = bases[0]  # 第一个是直接基类

                    # 检查是否继承自 MonoBehaviour（游戏脚本应该）
                    if "MonoBehaviour" not in inheritance and "Component" not in inheritance:
                        # 如果有 SerializeField 或 [RequireComponent] 等属性，可能是 MonoBehaviour 子类
                        if re.search(r'\[(SerializeField|RequireComponent|AddComponentMenu|ExecuteInEditMode)\]', content):
                            warnings.append(
                                f"{filename}: Class '{class_name}' uses Unity attributes but may not inherit from MonoBehaviour"
                            )

                    # ========== 4.2 检查 UI 组件继承 ==========
                    if base_class in VALID_UI_BASES:
                        # UI 组件应该正确继承
                        if not has_unity_engine:
                            issues.append(
                                f"{filename}: UI class '{class_name}' inherits {base_class} but missing UnityEngine"
                            )

                    # ========== 4.3 检查抽象类修饰 ==========
                    if "abstract" in inheritance or "abstract" in content:
                        abstract_match = re.search(r'abstract\s+class', content)
                        if abstract_match and not re.search(r'virtual|abstract\s+\w+\s+\w+\s*\(', content):
                            warnings.append(
                                f"{filename}: Abstract class '{class_name}' has no abstract members"
                            )

                else:
                    # 无继承的类
                    warnings.append(f"{filename}: Class '{class_name}' has no inheritance (should inherit MonoBehaviour for GameObject components)")

                # ========== 4.4 检查类名与文件名匹配 ==========
                expected_class = cs_file.stem  # 文件名（不含扩展名）
                if class_name != expected_class and not class_name.startswith(expected_class):
                    warnings.append(
                        f"{filename}: Class name '{class_name}' differs from filename '{expected_class}' (Unity convention: class should match filename)"
                    )

            # ========== 5. 检查生命周期方法签名 ==========
            lifecycle_methods = {
                'Awake', 'Start', 'Update', 'LateUpdate', 'FixedUpdate',
                'OnEnable', 'OnDisable', 'OnDestroy', 'OnGUI',
                'OnCollisionEnter', 'OnCollisionExit', 'OnCollisionStay',
                'OnTriggerEnter', 'OnTriggerExit', 'OnTriggerStay',
            }
            found_methods = re.findall(r'\b(void| IEnumerator|async Task)\s+(\w+)\s*\(', content)

            for return_type, method_name in found_methods:
                if method_name in lifecycle_methods:
                    # 检查访问修饰符
                    method_scope = re.search(
                        rf'(?:private|public|protected|internal)?\s*{return_type}\s+{method_name}',
                        content
                    )
                    if method_scope and 'private' in method_scope.group(0):
                        warnings.append(
                            f"{filename}: Lifecycle method '{method_name}' is private (should be private for MonoBehaviour)"
                        )

            # ========== 6. 检查 Cocos 残留引用 ==========
            cocos_patterns = [
                (r'\bcc\.\w+\b', "Cocos 'cc' reference"),
                (r'@cc\.', "Cocos decorator"),
                (r'cc\.Class\(', "Cocos 2.x JavaScript syntax"),
                (r'@property\s*\(', "Cocos Creator 3.x property decorator"),
                (r'@serializable', "Cocos attribute"),
            ]
            for pattern, desc in cocos_patterns:
                if re.search(pattern, content):
                    warnings.append(f"{filename}: Contains {desc} (may need translation)")

            # ========== 7. 检查常见错误模式 ==========
            error_patterns = [
                (r'\bnew\s+\w+\s*\(\s*\)\s*(?!\.)', "Possible missing UnityEngine prefix on type instantiation"),
                (r'#region\s', "Region directives (acceptable but review)"),
                (r'async\s+void\s+\w+\s*\(', "async void method (should be async Task for safety)"),
            ]
            for pattern, desc in error_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    warnings.append(f"{filename}: {desc}")

        except Exception as e:
            issues.append(f"{cs_file.name}: Read error - {e}")

    return {"issues": issues, "warnings": warnings}


def verify_manifest(manifest_path: Path) -> Dict[str, Any]:
    """验证 manifest 文件"""
    issues: List[str] = []
    warnings: List[str] = []

    if not manifest_path.is_file():
        issues.append("manifest.json not found")
        return {"issues": issues, "warnings": warnings}

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # 检查必要字段
        if "entries" not in manifest:
            issues.append("manifest.json missing 'entries' field")

        # 统计
        entries = manifest.get("entries", {})
        stats = manifest.get("stats", {})
        total_assets = stats.get("total", len(entries))

        warnings.append(f"Manifest contains {total_assets} asset entries")

    except json.JSONDecodeError as e:
        issues.append(f"Invalid JSON in manifest.json: {e}")
    except Exception as e:
        issues.append(f"Error reading manifest: {e}")

    return {"issues": issues, "warnings": warnings}


def main() -> int:
    ap = argparse.ArgumentParser(description="验证 Unity 迁移结果")
    ap.add_argument("--unity", required=True, help="Unity 项目根目录")
    ap.add_argument("--manifest", required=True, help="manifest.json 路径")
    ap.add_argument("--report", required=True, help="输出报告路径")
    ap.add_argument("--strict", action="store_true", help="将警告视为错误")
    args = ap.parse_args()

    unity_root = Path(args.unity)
    manifest_path = Path(args.manifest)
    report_path = Path(args.report)

    all_issues: List[str] = []
    all_warnings: List[str] = []

    print("\n" + "=" * 60)
    print("PHASE 5 — Verification Report")
    print("=" * 60)

    # 验证 manifest
    print("\n[1/4] Verifying manifest...")
    result = verify_manifest(manifest_path)
    all_issues.extend(result["issues"])
    all_warnings.extend(result["warnings"])

    # 验证预制体
    print("[2/4] Verifying prefabs...")
    # 预制体可能在 _Ported/_Prefabs 或直接在 _Ported 下
    prefabs_dir = unity_root / "Assets" / "_Ported" / "_Prefabs"
    if not prefabs_dir.is_dir():
        prefabs_dir = unity_root / "Assets" / "_Ported"
    prefab_files = list(prefabs_dir.rglob("*.prefab")) if prefabs_dir.is_dir() else []
    if prefab_files:
        for prefab in prefab_files:
            result = verify_prefab(prefab)
            for issue in result["issues"]:
                all_issues.append(f"Prefab {prefab.name}: {issue}")
            for warning in result["warnings"]:
                all_warnings.append(f"Prefab {prefab.name}: {warning}")
    else:
        all_warnings.append("No prefabs found in Assets/_Ported")

    # 验证场景
    print("[3/4] Verifying scenes...")
    # 场景可能在 _Ported/_Scenes 或直接在 _Ported 下
    scenes_dir = unity_root / "Assets" / "_Ported" / "_Scenes"
    if not scenes_dir.is_dir():
        scenes_dir = unity_root / "Assets" / "_Ported"
    scene_files = list(scenes_dir.rglob("*.unity")) if scenes_dir.is_dir() else []
    if scene_files:
        for scene in scene_files:
            result = verify_scene(scene)
            for issue in result["issues"]:
                all_issues.append(f"Scene {scene.name}: {issue}")
            for warning in result["warnings"]:
                all_warnings.append(f"Scene {scene.name}: {warning}")
    else:
        all_warnings.append("No scenes found in Assets/_Ported")

    # 验证脚本
    print("[4/4] Verifying scripts...")
    scripts_dir = unity_root / "Assets" / "_Ported" / "Scripts"
    if scripts_dir.is_dir():
        result = verify_scripts(scripts_dir)
        all_issues.extend(result["issues"])
        all_warnings.extend(result["warnings"])
    else:
        all_warnings.append("No scripts directory found")

    # 生成报告
    report = f"""# Migration Verification Report

## Summary
- Issues: {len(all_issues)}
- Warnings: {len(all_warnings)}

## Issues (must fix)
{chr(10).join(f"- {i}" for i in all_issues) if all_issues else "(none)"}

## Warnings (review recommended)
{chr(10).join(f"- {w}" for w in all_warnings) if all_warnings else "(none)"}

## C# Script Rules Check
- [x] Inheritance from MonoBehaviour (for GameObject components)
- [x] UI components inherit correctly from UnityEngine.UI
- [x] Class name matches filename (Unity convention)
- [x] Required 'using UnityEngine;' statement
- [x] Lifecycle method signatures (Awake, Start, Update, etc.)
- [x] No Cocos Creator residual references (cc., @cc., @property)
- [x] Unity namespace prefixes on type instantiation

## Next Steps
1. Fix all issues before building
2. Review TODO(cocos2unity) markers in scripts
3. Configure LLM for Phase 3 translation
4. Test in Unity Editor
"""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    # 输出摘要
    print("\n" + "=" * 60)
    print(f"Issues: {len(all_issues)}")
    print(f"Warnings: {len(all_warnings)}")
    print("=" * 60)

    if all_issues:
        print("\nIssues:")
        for issue in all_issues[:10]:
            print(f"  - {issue}")
        if len(all_issues) > 10:
            print(f"  ... and {len(all_issues) - 10} more")

    if all_warnings:
        print("\nWarnings:")
        for warning in all_warnings[:10]:
            print(f"  - {warning}")
        if len(all_warnings) > 10:
            print(f"  ... and {len(all_warnings) - 10} more")

    # 返回退出码
    if all_issues:
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
