#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Phase 3 — AI 驱动脚本翻译

直接让 LLM 读取 Cocos TS/JS 源码，按 Unity 生命周期重写为 C#。
不依赖正则解析类名，直接将完整源码作为上下文传给 LLM。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# LLM 配置
_llm_config: dict = {"provider": None}


def configure_llm(provider: str, **kwargs) -> None:
    """配置 LLM 提供商"""
    _llm_config["provider"] = provider
    _llm_config.update(kwargs)


def _load_api_mapping() -> str:
    """加载 API 映射表"""
    candidates = [
        Path(__file__).parent.parent / "references" / "api-mapping.md",
    ]
    for p in candidates:
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return ""


def _generate_skeleton_from_ts(src_text: str, filename: str) -> str:
    """
    从 Cocos TS/JS 源码静态提取类骨架，生成方法体为空的 C# 脚本。
    保留：类名、继承关系、字段（转 SerializeField）、方法签名（转空实现）。
    """
    class_name = _safe_class_name(filename)

    # 判断是 2.x (cc.Class) 还是 3.x (@ccclass)
    is_cc3 = "@ccclass" in src_text or "@property(" in src_text
    is_cc2 = "cc.Class(" in src_text

    fields: List[Tuple[str, str, Optional[str]]] = []  # (name, ts_type, default)
    methods: List[Tuple[str, List[str], str]] = []  # (name, args, return_type)
    base_class = "MonoBehaviour"
    extends_match = None

    if is_cc3:
        # Cocos 3.x: 提取 @property 字段
        # @property({type: CCInteger})
        # speed: number = 100;
        prop_pattern = r'@property\s*(?:\([^)]*\))?\s*\n\s*(\w+)\s*:\s*(\w+)(?:\s*=\s*([^;\n]+))?'
        for m in re.finditer(prop_pattern, src_text):
            name, ts_type, default = m.group(1), m.group(2), m.group(3)
            fields.append((name, ts_type, default))

        # 提取方法
        method_pattern = r'(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*(?::\s*(\w+))?\s*{'
        for m in re.finditer(method_pattern, src_text):
            name, args, ret = m.group(1), m.group(2), m.group(3) or "void"
            if name in ('constructor', 'ccclass', 'property'):
                continue
            methods.append((name, _parse_args(args), ret))

    elif is_cc2:
        # Cocos 2.x: cc.Class({ extends: cc.Component, properties: { ... }, ... })
        # 提取 properties
        props_match = re.search(r'properties\s*:\s*\{([^}]+)\}', src_text, re.DOTALL)
        if props_match:
            props_block = props_match.group(1)
            # 匹配: foo: 123 或 foo: { default: 123, type: cc.Integer }
            for line in props_block.split(','):
                line = line.strip()
                if not line:
                    continue
                # 简单属性: name: value
                simple = re.match(r'(\w+)\s*:\s*(.+)', line)
                if simple:
                    name, val = simple.group(1), simple.group(2).strip()
                    ts_type = _infer_type_from_value(val)
                    fields.append((name, ts_type, val if not val.startswith('{') else None))

        # 提取 extends
        extends_match = re.search(r'extends\s*:\s*(\w+)', src_text)

        # 提取方法 (name: function() {} 或 name() {})
        method_pattern = r'(\w+)\s*:\s*function\s*\(([^)]*)\)'
        for m in re.finditer(method_pattern, src_text):
            name, args = m.group(1), m.group(2)
            if name == 'properties':
                continue
            methods.append((name, _parse_args(args), "void"))

        # 也匹配 ES6 简写方法
        method_pattern2 = r'(\w+)\s*\(([^)]*)\)\s*{'
        for m in re.finditer(method_pattern2, src_text):
            name, args = m.group(1), m.group(2)
            if name in ('cc', 'Class', 'function'):
                continue
            # 去重
            if not any(m[0] == name for m in methods):
                methods.append((name, _parse_args(args), "void"))

    else:
        # 未知格式，尝试通用提取
        # 提取 var/let/const 字段
        var_pattern = r'(?:var|let|const)\s+(\w+)\s*:\s*(\w+)(?:\s*=\s*([^;\n]+))?'
        for m in re.finditer(var_pattern, src_text):
            fields.append((m.group(1), m.group(2), m.group(3)))

    # 生成 C# 代码
    lines = [
        "// Auto-generated SKELETON by cocos-to-unity (Phase 3)",
        "// Reason: No LLM API configured — class structure preserved, logic stripped",
        f"// Source: {filename}",
        "// Action: Fill in method bodies or configure LLM for full translation",
        "using UnityEngine;",
        "using UnityEngine.UI;",
        "",
        f"public class {class_name} : {base_class}",
        "{",
    ]

    # C# 保留关键字（不能用作标识符）
    cs_keywords = {
        'abstract', 'as', 'base', 'bool', 'break', 'byte', 'case', 'catch',
        'char', 'checked', 'class', 'const', 'continue', 'decimal', 'default',
        'delegate', 'do', 'double', 'else', 'enum', 'event', 'explicit',
        'extern', 'false', 'finally', 'fixed', 'float', 'for', 'foreach',
        'goto', 'if', 'implicit', 'in', 'int', 'interface', 'internal',
        'is', 'lock', 'long', 'namespace', 'new', 'null', 'object', 'operator',
        'out', 'override', 'params', 'private', 'protected', 'public',
        'readonly', 'ref', 'return', 'sbyte', 'sealed', 'short', 'sizeof',
        'stackalloc', 'static', 'string', 'struct', 'switch', 'this', 'throw',
        'true', 'try', 'typeof', 'uint', 'ulong', 'unchecked', 'unsafe',
        'ushort', 'using', 'virtual', 'void', 'volatile', 'while',
        'add', 'alias', 'ascending', 'async', 'await', 'descending',
        'dynamic', 'from', 'get', 'global', 'group', 'into', 'join',
        'let', 'nameof', 'on', 'orderby', 'partial', 'remove', 'select',
        'set', 'value', 'var', 'when', 'where', 'yield',
        'name',  # 常见字段名但 C# 中会引起问题
    }

    # 字段
    if fields:
        lines.append("    // Fields (ported from Cocos properties)")
        for field_name, ts_type, default in fields:
            safe_name = field_name + '_' if field_name in cs_keywords else field_name
            cs_type = _ts_type_to_cs(ts_type)
            default_str = f" = {_convert_default(default, cs_type)}" if default else ""
            lines.append(f"    [SerializeField] private {cs_type} {safe_name}{default_str};")
        lines.append("")

    # 生命周期方法映射
    lifecycle_map = {
        'onLoad': 'void Start()',
        'start': 'void Start()',
        'update': 'void Update()',
        'lateUpdate': 'void LateUpdate()',
        'onDestroy': 'void OnDestroy()',
        'onEnable': 'void OnEnable()',
        'onDisable': 'void OnDisable()',
        '_ctor': 'void Awake()',
    }

    # 方法
    if methods:
        lines.append("    // Methods (ported from Cocos)")
        for method_name, args, ret in methods:
            if method_name in lifecycle_map:
                sig = lifecycle_map[method_name]
                lines.append(f"    {sig}")
            else:
                cs_ret = _ts_type_to_cs(ret) if ret != "void" else "void"
                arg_str = ", ".join(f"{t} {n}" for t, n in args)
                safe_method_name = method_name + '_' if method_name in cs_keywords else method_name
                lines.append(f"    {cs_ret} {safe_method_name}({arg_str})")
            lines.append("    {")
            lines.append("        // TODO(cocos2unity): implement")
            if ret and ret != "void":
                lines.append(f"        return default({_ts_type_to_cs(ret)});")
            lines.append("    }")
            lines.append("")

    lines.append("}")

    return "\n".join(lines)


def _parse_args(args_str: str) -> List[Tuple[str, str]]:
    """解析参数列表 'a: number, b: string' -> [(number, a), (string, b)]"""
    result = []
    for arg in args_str.split(','):
        arg = arg.strip()
        if not arg:
            continue
        # 匹配 name: type 或 name
        m = re.match(r'(\w+)(?:\s*:\s*(\w+))?', arg)
        if m:
            name, ts_type = m.group(1), m.group(2) or "object"
            result.append((_ts_type_to_cs(ts_type), name))
    return result


def _ts_type_to_cs(ts_type: Optional[str]) -> str:
    """TS 类型转 C# 类型"""
    if not ts_type:
        return "object"
    mapping = {
        'number': 'float',
        'Number': 'float',
        'string': 'string',
        'String': 'string',
        'boolean': 'bool',
        'bool': 'bool',
        'Boolean': 'bool',
        'any': 'object',
        'void': 'void',
        'integer': 'int',
        'Integer': 'int',
        'cc.Vec2': 'Vector2',
        'Vec2': 'Vector2',
        'cc.Vec3': 'Vector3',
        'Vec3': 'Vector3',
        'cc.Color': 'Color',
        'Color': 'Color',
        'cc.Node': 'GameObject',
        'Node': 'GameObject',
    }
    return mapping.get(ts_type, ts_type)


def _infer_type_from_value(val: str) -> str:
    """从默认值推断类型"""
    val = val.strip()
    if val.startswith('"') or val.startswith("'"):
        return 'string'
    if val in ('true', 'false'):
        return 'bool'
    if re.match(r'^-?\d+$', val):
        return 'int'
    if re.match(r'^-?\d+\.\d+$', val):
        return 'float'
    if val.startswith('['):
        return 'object[]'
    if val.startswith('{'):
        return 'object'
    return 'object'


def _convert_default(val: Optional[str], cs_type: str) -> str:
    """转换默认值到 C# 语法"""
    if not val:
        return ""
    val = val.strip()
    if val.startswith('"') or val.startswith("'"):
        return val  # 字符串
    if val in ('true', 'false'):
        return val
    if cs_type == 'string' and not val.startswith('"'):
        return f'"{val}"'
    return val


# ============================================================================
# 核心翻译函数
# ============================================================================

def translate_file(src_text: str, filename: str, no_stub: bool = False) -> Tuple[str, List[str]]:
    """
    直接让 LLM 读取源码并重写为 Unity C#。

    Args:
        src_text: 原始 TS/JS 代码
        filename: 原始文件名
        no_stub: 如果为 True，无 API 时返回空字符串而不是生成 stub

    Returns:
        (csharp_source, notes)
    """
    # 自动检测 Cocos 版本
    if "@ccclass" in src_text or "@property(" in src_text:
        version = "Cocos Creator 3.x (TypeScript)"
    elif "cc.Class(" in src_text:
        version = "Cocos Creator 2.x (JavaScript)"
    else:
        version = "Cocos Creator (unknown version)"

    api_mapping = _load_api_mapping()

    # 构建 Prompt - 直接让 LLM 理解业务逻辑并重写
    system_prompt = f"""你是 Cocos Creator → Unity C# 迁移专家。

任务：将下面的 Cocos Creator 游戏脚本按照业务逻辑重写为 Unity C# MonoBehaviour。

【关键规则】
1. 提取并重写业务逻辑，不是逐字翻译
2. 生命周期映射：
   - _ctor → Awake
   - start → Start
   - update → Update
   - lateUpdate → LateUpdate
   - onLoad → Start
   - onDestroy → OnDestroy
   - onEnable → OnEnable
   - onDisable → OnDisable
3. 字段用 [SerializeField] 保留原始名称
4. 无法确定的逻辑用 `// TODO(cocos2unity): <描述>` 标注
5. SDK/广告代码生成空 Stub，不搬运实现
6. 使用 DOTween 处理动画
7. 输出纯 C# 代码，不需要 markdown 标记

【API 映射参考】
{api_mapping or "(使用你熟悉的 Cocos→Unity API 对应关系)"}

输出格式（直接输出 C# 代码，不要 markdown 标记）：
```csharp
// Auto-generated by cocos-to-unity
// Source: {filename}
using UnityEngine;
using UnityEngine.UI;

public class {_safe_class_name(filename)} : MonoBehaviour
{{
    [SerializeField] private int score = 0;

    void Awake() {{ /* 从 _ctor 迁移 */ }}
    void Start() {{ /* 从 onLoad/start 迁移 */ }}
    void Update() {{ /* 从 update 迁移 */ }}
}}
```

【命名规则】
- 类名必须严格等于文件名（不含扩展名）：{_safe_class_name(filename)}
- 一个文件只能有一个 public class
"""

    user_prompt = f"""【源文件信息】
文件格式：{version}
文件名：{filename}

【关键要求】
1. 生成的 C# 类名必须严格等于文件名（不含扩展名）：{_safe_class_name(filename)}
2. 一个 .cs 文件只能包含一个 public class，遵循单一职责原则
3. 如果源文件有多个类，只翻译主类（与文件名同名的类），其他类忽略或合并

【源代码】
{'-' * 60}
{src_text}
{'-' * 60}

请将上述 Cocos Creator 代码重写为 Unity C#，保持原有业务逻辑。
直接输出 C# 代码，不需要任何解释或 markdown 标记。
"""

    return _call_llm(system_prompt, user_prompt, src_text, filename)


def _call_llm(system_prompt: str, user_prompt: str, src_text: str, filename: str,
              no_stub: bool = False) -> Tuple[str, List[str]]:
    """
    调用 LLM API 进行翻译。

    Args:
        no_stub: 如果为 True，无 API 时返回空字符串而不是生成 stub
    """
    # 自动配置 LLM
    if not _llm_config.get("provider"):
        if os.environ.get("OPENAI_API_KEY"):
            configure_llm("openai",
                api_key=os.environ.get("OPENAI_API_KEY"),
                base_url=os.environ.get("OPENAI_BASE_URL"))
        elif os.environ.get("ANTHROPIC_API_KEY"):
            configure_llm("anthropic",
                api_key=os.environ.get("ANTHROPIC_API_KEY"))

    provider = _llm_config.get("provider")
    notes: List[str] = []

    if provider is None:
        # 无 LLM：生成骨架脚本（保留类结构，方法体为空）
        notes.append("No LLM — generated skeleton stub (structure preserved)")
        cs = _generate_skeleton_from_ts(src_text, filename)
        return cs, notes

    try:
        if provider == "openai":
            import openai
            client = openai.OpenAI(
                api_key=_llm_config.get("api_key"),
                base_url=_llm_config.get("base_url"),
            )
            response = client.chat.completions.create(
                model=_llm_config.get("model", "gpt-4o"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=8192,
            )
            cs = response.choices[0].message.content or ""

        elif provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(
                api_key=_llm_config.get("api_key"),
            )
            response = client.messages.create(
                model=_llm_config.get("model", "claude-3-5-sonnet-20241022"),
                max_tokens=8192,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            cs = "".join(block.text for block in response.content)

        # 清理 markdown 标记
        cs = re.sub(r"```\w*\n?", "", cs).strip()

        # 后处理：确保类名与文件名一致，且只有一个 public class
        cs = _normalize_class_name(cs, filename)

        # 统计 TODO 数量
        todo_count = cs.count("// TODO(cocos2unity):")
        if todo_count > 0:
            notes.append(f"LLM translated, {todo_count} TODO(s) need review")

        return cs, notes

    except Exception as e:
        # LLM 调用失败：降级为骨架生成
        notes.append(f"LLM failed — generated skeleton: {e}")
        cs = _generate_skeleton_from_ts(src_text, filename)
        return cs, notes


def _safe_class_name(filename: str) -> str:
    """从文件名提取安全的 C# 类名（与文件名完全一致，仅首字母大写）"""
    name = Path(filename).stem
    # 首字母大写，其余保持原样（C# 惯例）
    if name:
        return name[0].upper() + name[1:]
    return "GameClass"


def _extract_class_name_simple(filename: str) -> str:
    """简单从文件名提取类名（与文件名一致）"""
    return _safe_class_name(filename)


def translate_path(src: Path, out: Path, sdk_filter=None, no_stub: bool = False,
                   script_mapping: dict = None) -> List[str]:
    """
    翻译单个脚本文件

    Args:
        src: 源文件路径
        out: 输出文件路径
        sdk_filter: SDK 过滤器
        no_stub: 是否跳过 stub 生成
        script_mapping: 用于记录未生成脚本的映射 dict[script_name] = cocos_uuid
    """
    src_text = src.read_text(encoding="utf-8", errors="ignore")

    # SDK 过滤
    if sdk_filter:
        try:
            is_sdk, reasons = sdk_filter.should_exclude_script(src)
            if is_sdk:
                if no_stub:
                    if script_mapping is not None:
                        script_mapping[src.stem] = "SDK"
                    return [f"STUB: SDK excluded (skipped)"]
                else:
                    class_name = _safe_class_name(src.name)
                    stub = f"""// STUB by cocos-to-unity
// SDK/ad script excluded: {'; '.join(reasons)}
using UnityEngine;

public class {class_name} : MonoBehaviour
{{
    // SDK/ad code stripped
}}
"""
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(stub, encoding="utf-8")
                    return [f"STUB: SDK excluded"]
        except Exception:
            pass  # SDK 过滤失败，继续翻译

    cs, notes = translate_file(src_text, src.name, no_stub)

    # 记录未生成脚本
    if script_mapping is not None and not cs:
        script_mapping[src.stem] = "NO_STUB"

    # 只有生成内容时才写入文件
    if cs:
        out.parent.mkdir(parents=True, exist_ok=True)
        header = ""
        if notes:
            header = "// Translation notes:\n" + "\n".join(f"//   - {n}" for n in notes) + "\n\n"
        out.write_text(header + cs, encoding="utf-8")

        # 生成 .meta 文件（包含唯一 GUID）
        import hashlib
        import random
        guid = hashlib.md5(str(out).encode()).hexdigest()
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
        out.with_suffix('.cs.meta').write_text(meta_content, encoding="utf-8")

    return notes


def _normalize_class_name(cs: str, filename: str) -> str:
    """
    确保生成的 C# 代码：
    1. 类名与文件名一致
    2. 只有一个 public class
    """
    expected_name = _safe_class_name(filename)

    # 查找所有 public class 声明
    pattern = r'public\s+class\s+(\w+)'
    matches = list(re.finditer(pattern, cs))

    if not matches:
        return cs

    if len(matches) == 1:
        # 只有一个类，确保类名正确
        actual_name = matches[0].group(1)
        if actual_name != expected_name:
            cs = cs.replace(f'public class {actual_name}', f'public class {expected_name}', 1)
        return cs

    # 多个 public class：保留与文件名同名的，其他的改为 internal
    result_lines = []
    for line in cs.split('\n'):
        match = re.search(r'public\s+class\s+(\w+)', line)
        if match:
            class_name = match.group(1)
            if class_name != expected_name:
                # 将其他 public class 改为 internal
                line = line.replace('public class', 'internal class', 1)
                # 添加注释说明
                line = f'// TODO(cocos2unity): 此类应从单独文件提取\n{line}'
        result_lines.append(line)

    return '\n'.join(result_lines)


# ============================================================================
# CLI 入口
# ============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3 — AI 驱动脚本翻译")
    ap.add_argument("--cocos", required=True, help="Cocos 项目根目录")
    ap.add_argument("--unity", required=True, help="Unity 项目根目录")
    ap.add_argument("--strip-sdk", action="store_true", help="跳过 SDK 脚本")
    ap.add_argument("--no-stub", action="store_true",
                    help="无 LLM 时跳过脚本生成（不生成 stub）")
    ap.add_argument("--output-mapping", default=None,
                    help="输出未映射脚本列表到 JSON 文件")
    args = ap.parse_args()

    cocos_root = Path(args.cocos)
    unity_root = Path(args.unity)
    out_dir = unity_root / "Assets" / "_Ported" / "Scripts"
    no_stub = args.no_stub

    # 查找脚本目录
    src_dir = None
    for cand in [cocos_root / "assets" / "scripts", cocos_root / "assets"]:
        if cand.is_dir():
            scripts = list(cand.rglob("*.ts")) + list(cand.rglob("*.js"))
            scripts = [s for s in scripts if not s.name.endswith(".d.ts")]
            if scripts:
                src_dir = cand
                break

    if not src_dir:
        print("No scripts found. Skipping Phase 3.")
        return 0

    # SDK 过滤
    sdk_filt = None
    if args.strip_sdk:
        try:
            from sdk_filter import SdkFilter
            sdk_filt = SdkFilter()
        except ImportError:
            pass

    # 记录未映射脚本
    script_mapping: dict = {}

    total = 0
    skipped = 0
    for ext in ("*.ts", "*.js"):
        for src_file in src_dir.rglob(ext):
            if src_file.name.endswith(".d.ts"):
                continue
            rel = src_file.relative_to(src_dir).with_suffix(".cs")
            try:
                notes = translate_path(src_file, out_dir / rel, sdk_filt, no_stub, script_mapping)
                if notes and "skipped" in notes[0].lower():
                    skipped += 1
                    print(f"  [SKIP] {src_file.name} -> {rel} ({notes[0]})")
                else:
                    is_stub = any("STUB:" in n or "TODO" in n for n in notes)
                    tag = "[STUB] " if is_stub else ""
                    print(f"  {tag}{src_file.name} -> {rel} ({len(notes)} notes)")
                    total += 1
            except Exception as e:
                print(f"  ERROR {src_file.name}: {e}", file=sys.stderr)

    # 输出未映射脚本列表
    if script_mapping and args.output_mapping:
        import json
        out_path = Path(args.output_mapping)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(script_mapping, f, indent=2, ensure_ascii=False)
        print(f"\nSaved unmapped scripts to: {out_path}")

    print(f"\nPhase 3 complete: {total} scripts processed, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
