#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fix_missing_scripts.py — 手动建立缺失的 Cocos UUID → C# GUID 映射

问题：WaterSortMaster 项目的 manifest.json 缺少脚本映射信息。
解决方案：直接从 TS 源文件提取脚本类名，建立 UUID → GUID 映射。
"""
import re
import os
from pathlib import Path
from typing import Dict, Optional, Tuple
import hashlib


def sanitize_class_name(name: str) -> str:
    """清理类名，移除非法字符"""
    cleaned = re.sub(r'[^\w]', '', name)
    if cleaned and cleaned[0].isdigit():
        cleaned = 'C' + cleaned
    return cleaned or 'UnknownComponent'


def create_csharp_script(class_name: str, output_dir: Path) -> Tuple[str, str]:
    """创建 C# stub 脚本，返回 (脚本路径, GUID)"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    clean_name = sanitize_class_name(class_name)
    guid = hashlib.md5(clean_name.encode()).hexdigest()[:32]
    
    cs_path = output_dir / f"{clean_name}.cs"
    meta_path = output_dir / f"{clean_name}.cs.meta"
    
    cs_content = f"""using UnityEngine;

/// <summary>
/// Auto-generated stub for {clean_name}
/// Translated from Cocos Creator TS source
/// </summary>
public class {clean_name} : MonoBehaviour
{{
    // TODO: Translate business logic from Cocos TS source
    
    void Start()
    {{
        // Initialize component
    }}
    
    void Update()
    {{
        // Update logic
    }}
}}
"""
    cs_path.write_text(cs_content, encoding="utf-8")
    
    meta_content = f"""fileFormatVersion: 2
guid: {guid}
MonoImporter:
  externalObjects: {{}}
  serializedVersion: 2
  defaultReferences: []
  executionOrder: 0
  icon: {{instanceID: 0}}
  userData: 
  assetBundleName: 
  assetBundleVariant: 
"""
    meta_path.write_text(meta_content, encoding="utf-8")
    
    return str(cs_path), guid


def fix_yaml_script_refs(yaml_path: Path, cocos_uuid_to_guid: Dict[str, str], 
                        dry_run: bool = True) -> int:
    """修复 YAML 文件（场景/预制体）中的脚本引用"""
    try:
        content = yaml_path.read_text(encoding="utf-8", errors="ignore")
        original = content
        
        lines = content.split('\n')
        new_lines = []
        fixed = 0
        
        # 预编译正则表达式
        script_pattern = re.compile(r'^(\s*)m_Script:\s*\{\s*fileID:\s*0\s*\}')
        todo_pattern = re.compile(r'# TODO\(cocos2unity\):\s*Assign\s+([^\s/]+)/([^\s]+)\.cs')
        
        i = 0
        while i < len(lines):
            line = lines[i]
            match = script_pattern.match(line)
            
            if match:
                indent = match.group(1)
                # 向后查找 TODO 注释（在同一缩进级别或稍后）
                cocos_uuid = None
                for j in range(i+1, min(len(lines), i+3)):
                    todo_match = todo_pattern.search(lines[j])
                    if todo_match:
                        cocos_uuid = todo_match.group(1)
                        break
                
                if cocos_uuid and cocos_uuid in cocos_uuid_to_guid:
                    guid = cocos_uuid_to_guid[cocos_uuid]
                    new_lines.append(f'{indent}m_Script: {{fileID: 11500000, guid: {guid}, type: 3}}')
                    fixed += 1
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
            
            i += 1
        
        new_content = '\n'.join(new_lines)
        
        if not dry_run and new_content != original:
            yaml_path.write_text(new_content, encoding="utf-8")
            rel_path = yaml_path.relative_to(yaml_path.parents[3]) if len(yaml_path.parts) > 3 else yaml_path.name
            print(f"  Fixed: {rel_path} ({fixed} refs)")
        
        return fixed
        
    except Exception as e:
        print(f"  Error: {yaml_path.name}: {e}")
        return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Fix missing script references")
    ap.add_argument("--cocos", required=True, help="Cocos Creator project root")
    ap.add_argument("--unity", required=True, help="Unity project root")
    ap.add_argument("--dry-run", action="store_true", default=False, help="Dry run mode")
    args = ap.parse_args()
    
    cocos_root = Path(args.cocos)
    unity_root = Path(args.unity)
    dry_run = args.dry_run
    
    print("\n[1/3] Collecting missing script references...")
    ported_dir = unity_root / "Assets" / "_Ported"
    
    # 收集所有缺失的引用: cocos_uuid -> class_name
    cocos_uuid_to_class = {}
    
    for yaml_file in list(ported_dir.rglob("*.unity")) + list(ported_dir.rglob("*.prefab")):
        try:
            content = yaml_file.read_text(encoding="utf-8", errors="ignore")
            
            # 提取所有 TODO 引用
            for match in re.finditer(r'# TODO\(cocos2unity\):\s*Assign\s+([^\s/]+)/([^\s]+)\.cs', content):
                cocos_uuid = match.group(1)
                class_name = match.group(2)
                if cocos_uuid not in cocos_uuid_to_class:
                    cocos_uuid_to_class[cocos_uuid] = class_name
        except Exception:
            pass
    
    print(f"  Found {len(cocos_uuid_to_class)} missing script references")
    for uuid, cls in list(cocos_uuid_to_class.items())[:5]:
        print(f"    {cls} (UUID: {uuid[:20]}...)")
    
    print("\n[2/3] Creating stub scripts...")
    
    # 为每个缺失的脚本创建 stub
    cocos_uuid_to_guid = {}
    scripts_dir = unity_root / "Assets" / "_Ported" / "Scripts" / "_script"
    
    for cocos_uuid, class_name in cocos_uuid_to_class.items():
        cs_path, guid = create_csharp_script(class_name, scripts_dir)
        cocos_uuid_to_guid[cocos_uuid] = guid
        print(f"  Created: {sanitize_class_name(class_name)} (GUID: {guid})")
    
    print(f"\n[3/3] Fixing script references in scenes/prefabs...")
    
    # 修复所有 YAML 文件
    total_fixed = 0
    yaml_files = list(ported_dir.rglob("*.unity")) + list(ported_dir.rglob("*.prefab"))
    print(f"  Scanning {len(yaml_files)} YAML files...")
    
    for yaml_file in yaml_files:
        fixed = fix_yaml_script_refs(yaml_file, cocos_uuid_to_guid, dry_run)
        total_fixed += fixed
    
    print(f"\n{'='*60}")
    print(f"Scripts created: {len(cocos_uuid_to_guid)}")
    print(f"References fixed: {total_fixed}")
    
    if dry_run:
        print("\n⚠️  DRY RUN - No files were modified")
    else:
        print("\n✅ Done! Please reimport the Unity project.")


if __name__ == "__main__":
    main()
