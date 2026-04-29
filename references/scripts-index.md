# Scripts Index

所有脚本均为**幂等**的，支持 `--dry-run`（如适用），仅使用 Python 标准库，并输出结构化结果。

| 脚本 | 用途 | 阶段 |
|---|---|---|
| `scripts/pipeline.py` | **统一入口** — 一键运行所有 6 个阶段 | 0-5 |
| `scripts/migrate_assets.py` | 迁移媒体资源 + 生成 Unity .meta + 制作清单 + 9宫格/图集提取 | 1 |
| `scripts/convert_prefab.py` | **批量转换所有 Prefab/Scene** → Unity 原生 .prefab/.unity YAML | 2 |
| `scripts/convert_scene.py` | 单个 Cocos 场景/预制体 → 中间格式 plan.json | 2 |
| `scripts/apply_plan.py` | plan.json → Unity YAML 或 Editor 脚本 | 2 |
| `scripts/convert_widget.py` | plan.json → 自动应用 Widget 锚点的编辑器脚本 | 2/4 |
| `scripts/translator.py` | **AI 驱动翻译** — 调用 LLM 完成 TS/JS → C# MonoBehaviour；无 LLM 时降级为骨架生成 | 3 |
| `scripts/link_scripts.py` | **脚本关联** — 将 Prefab/Scene 中的 `m_Script: {fileID: 0}` 替换为正确 GUID | 3.5 |
| `scripts/fix_class_names.py` | **类名校准** — 批量修复 `.cs` 类名与文件名不一致问题 | 3/5 |
| `scripts/fix_missing_scripts.py` | **缺失脚本修复** — 手动建立 Cocos UUID → C# GUID 映射并创建 Stub | 3.5 |
| `scripts/verify_migration.py` | **迁移验证** — 检查预制体/场景/脚本完整性、null GUID、类名匹配 | 5 |
| `scripts/convert_anim.py` | Cocos .anim → Unity AnimationClip YAML (支持批量) | 4 |
| `scripts/sdk_filter.py` | SDK/广告/统计内容过滤工具 | 0-3 |
| `scripts/selective_migrate.py` | **选择性迁移** — 仅迁移指定场景及其依赖资源 | A-D |

## 核心自动化增强

### 1. 自动脚本溯源 (convert_scene.py / convert_prefab.py / link_scripts.py)
工具现在会自动扫描 Cocos 项目的 `library/imports` 目录：
- **逻辑**：通过正则提取 `cc._RF.push` 调用，自动建立从压缩 UUID 到原始类名的映射。
- **优点**：无需手动维护 `UUID_SCRIPT_MAP`，自动识别所有自定义组件并匹配 Unity C# GUID。
- **UUID 正则注意**：Cocos UUID 为 Base64 变体，含 `+` 和 `/` 字符，正则必须匹配 `[a-zA-Z0-9+/]`。

### 2. Unity 2022 格式对齐 (convert_prefab.py)
- **Canvas**：自动补全 `serializedVersion: 3` 和 `m_UpdateRectTransformForStandalone`，解决组件失效问题。
- **MonoBehaviour**：自动移除非标准的 `m_Name` 字段，消除 Inspector 面板中的“异常脚本”提示。

### 3. 脚本翻译质量保障 (translator.py)
- **骨架生成模式**：无 LLM API 时，静态解析 TS/JS 提取类结构（字段→`[SerializeField]`、方法签名→空实现 + `// TODO`），保留完整继承关系，pipeline 仍可完整运行。
- **单一职责 enforcement**：`_normalize_class_name()` 强制确保一个文件只有一个 `public class`，多余的类自动改为 `internal`。
- **类名一致性**：`_safe_class_name()` 强制类名与文件名完全一致。

## 常用命令参考

### 全量流水线
```bash
python scripts/pipeline.py --cocos <cocos-root> --unity <unity-root> --atlas --convert-pos --ppu 100
```

### 批量转换 Prefab/Scene (推荐)
```bash
python scripts/convert_prefab.py --src <cocos-root>/assets --dst <unity-root>/Assets/_Ported --manifest manifest.json --convert-pos --ppu 100
```

### 选择性迁移单个场景
```bash
python scripts/selective_migrate.py --cocos <cocos-root> --unity <unity-root> --target assets/scenes/Game.fire
```

## 注意事项
- **翻译模式**：`translator.py` 调用 LLM 自动完成 TS/JS → C# 翻译，参考 `references/api-mapping.md` 的 API 映射。
- **坐标系统**：UI 节点默认保持像素单位，世界节点根据 `--ppu` 参数进行缩放转换。
