#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fix_class_names.py
批量修复 C# 脚本的类名，使其与文件名一致。
遵循 Unity 单一职责原则：一个文件一个类，类名=文件名。
"""
import re
from pathlib import Path

def fix_class_name(cs_file: Path) -> bool:
    """修复单个 .cs 文件的类名，返回是否修改"""
    if not cs_file.suffix == '.cs':
        return False
    if cs_file.name.endswith('.meta'):
        return False

    filename = cs_file.stem  # 文件名（不含扩展名）

    content = cs_file.read_text(encoding='utf-8')

    # 匹配 class Xxx : MonoBehaviour 或 class Xxx: MonoBehaviour
    # 支持单行和多行格式
    pattern = r'class\s+\w+\s*:'
    match = re.search(pattern, content)
    if not match:
        return False

    # 提取现有类名
    existing_class = re.search(r'class\s+(\w+)\s*:', content)
    if not existing_class:
        return False

    old_class_name = existing_class.group(1)
    if old_class_name == filename:
        return False  # 已经一致，无需修改

    # 替换类名（只替换 class 声明中的）
    new_content = re.sub(
        rf'class\s+{re.escape(old_class_name)}\s*:',
        f'class {filename} :',
        content
    )

    cs_file.write_text(new_content, encoding='utf-8')
    print(f"  Fixed: {cs_file.relative_to(cs_file.parent.parent.parent)} - {old_class_name} → {filename}")
    return True

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python fix_class_names.py <unity_project_root>")
        return

    unity_root = Path(sys.argv[1])
    scripts_dir = unity_root / "Assets" / "_Ported" / "Scripts"

    if not scripts_dir.exists():
        print(f"Scripts directory not found: {scripts_dir}")
        return

    fixed_count = 0
    skipped_count = 0

    print(f"\nFixing class names in: {scripts_dir}\n")

    for cs_file in scripts_dir.rglob("*.cs"):
        if ".meta" in cs_file.name:
            skipped_count += 1
            continue
        if fix_class_name(cs_file):
            fixed_count += 1
        else:
            skipped_count += 1

    print(f"\nSummary: {fixed_count} fixed, {skipped_count} skipped")

if __name__ == "__main__":
    main()
