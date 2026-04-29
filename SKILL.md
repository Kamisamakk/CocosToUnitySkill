---
name: cocos-to-unity
description: Cocos 2.x/3.x -> Unity 2022 自动化迁移与逻辑重构。
version: 3.4
---

# Cocos → Unity 迁移技能

## 核心原则
- **严禁直译**：提取业务逻辑与数据流，基于 Unity 生命周期重载重构为 C#。
- **数据延续**：保持 `[SerializeField]` 字段名与 Cocos 属性名一致，确保序列化数据自动绑定。
- **静态挂载**：Phase 2 预制体转换时**直接写入**脚本 GUID，无需 Phase 5 二次关联。
- **单一职责**：每个 `.cs` 文件只定义一个 `public class`，类名必须与文件名完全一致（如 `GameScene.cs` → `public class GameScene`）。若源文件包含多个类，主类（与文件名同名）保持 `public`，其余类强制降级为 `internal`。

## 关键改进 (v3.4)
- **脚本 .meta 自动生成**：`translator.py` 在生成 `.cs` 文件时自动生成对应的 `.meta` 文件（包含唯一 GUID）
- **预制体直接引用**：Phase 2 转换时扫描脚本 GUID，直接写入 YAML 的 `m_Script` 字段
- **Phase 5 可选**：由于预制体转换时已直接引用，Phase 5 关联步骤成功率提升至 100%

## 自动化工具链
- **脚本溯源**：自动扫描 `library/imports` 提取 UUID -> ClassName 映射，无需手动维护。
- **YAML 对齐**：Canvas 组件自动补全 `serializedVersion: 3`，MonoBehaviour 自动移除非法字段。
- **资源迁移**：`scripts/migrate_assets.py` 处理图片与音效。
- **预制体转换**：`scripts/convert_prefab.py` 支持 Scene/Prefab 批量生成。
- **类名校准**：`scripts/fix_class_names.py` 批量修复类名与文件名不一致问题。
- **脚本关联**：`scripts/link_scripts.py` 将预制体/场景中的 `m_Script: {fileID: 0}` 替换为正确的 GUID 引用。
- **缺失脚本修复**：`scripts/fix_missing_scripts.py` 手动建立缺失的 Cocos UUID → C# GUID 映射并创建 Stub。
- **迁移验证**：`scripts/verify_migration.py`（Phase 7）检查预制体/场景/脚本的完整性、null GUID、类名匹配等。

## 脚本翻译（Phase 3 — AI 驱动）
- **核心模块**：`scripts/translator.py` — 调用 LLM API 完成 TS/JS → C# 翻译
- **LLM 配置**：支持 OpenAI（`OPENAI_API_KEY`）/ Anthropic（`ANTHROPIC_API_KEY`），自动从环境变量检测
- **Prompt 策略**：注入 `references/api-mapping.md` 作为上下文，确保 Cocos API 映射正确
- **输出质量**：严格可编译的 C# MonoBehaviour；无法翻译的逻辑以 `// TODO(cocos2unity):` 标注
- **SDK 过滤**：复用 `scripts/sdk_filter.py`，SDK 脚本自动生成 Stub
- **无 LLM 时**：自动降级为**骨架生成模式**——静态解析 TS/JS 提取类结构（字段→`[SerializeField]`、方法签名→空实现），保留完整继承关系；pipeline 仍可完整运行
- **单一职责 enforcement**：`_normalize_class_name()` 强制确保一个文件只有一个 `public class`，多余的类自动改为 `internal`
- **类名一致性**：`_safe_class_name()` 强制类名与文件名完全一致（首字母大写，其余保留原样）
- **类名校准**：翻译后执行 `scripts/fix_class_names.py` 确保类名与文件名一致

### CLI 选项
- `--no-stub`（默认 **False**）：无 LLM 时跳过脚本生成，仅记录脚本名到 `unmapped_scripts.json`
- `--generate-stub`：显式覆盖 `--no-stub`，强制生成骨架 Stub

## Phase 5 — 脚本关联（Prefab/Scene 挂载修复）
- **核心模块**：`scripts/link_scripts.py`
- **UUID 正则**：Cocos UUID 编码为 Base64 变体，含 `+` 和 `/` 字符；正则必须匹配 `[a-zA-Z0-9+/]`
- **映射建立**：自动从 `library/imports` 扫描 `cc._RF.push` 建立 UUID → ClassName 映射，再关联 Unity `.cs.meta` GUID
- **未映射处理**：无法映射的脚本名自动收集到 `unmapped_scripts.json`，后续可通过 `--resolve` 二次解析
- ** resolve 模式**：`python scripts/link_scripts.py --cocos <path> --unity <path> --resolve` — Unity 中生成脚本后自动查找并关联

## 关键 API 映射参考
- **UI**: `cc.UITransform` -> `RectTransform`; `cc.Canvas` -> `Canvas` + `CanvasScaler` (Match=1).
- **生命周期**: `_ctor`→`Awake`, `onLoad`→`Start`, `start`→`Start`, `update`→`Update`, `lateUpdate`→`LateUpdate`, `onEnable`→`OnEnable`, `onDisable`→`OnDisable`, `onDestroy`→`OnDestroy`.
- **SDK**: 仅保留 Stub 接口与 `Debug.Log`，严禁搬运具体实现。
- **详细映射**: 完整对应表见 `references/api-mapping.md`，已注入 translator.py 的 LLM prompt。

## Pipeline 执行顺序

```
Phase 0 (审计) → Phase 2 (脚本) → Phase 3 (资产) → Phase 4 (预制体) → Phase 5 (关联) → Phase 6 (动画) → Phase 7 (验证)
```

**执行顺序理由**：Phase 2 脚本先于 Phase 3 资产执行，确保 `.meta` 文件（GUID）在预制体转换前生成。

**各 Phase 说明**：
- **Phase 0**：项目审计，生成 `report.json`
- **Phase 2**：TS/JS → C# 脚本翻译，生成 `Scripts/` + `.meta` 文件
- **Phase 3**：媒体资源迁移（Sprite、Texture、Audio 等），生成 `manifest.json`
- **Phase 4**：预制体/场景 YAML 转换，生成 `_Prefabs/`、`_Scenes/`
- **Phase 5**：将 TODO 注释中的脚本引用替换为真实 GUID
- **Phase 6**：动画转换
- **Phase 7**：完整性验证
- **Phase 0**：项目审计，生成 `report.json`
- **Phase 3**：TS/JS → C# 脚本翻译，生成 `Scripts/` + `.meta` 文件
- **Phase 1**：媒体资源迁移（Sprite、Texture、Audio 等），生成 `manifest.json`
- **Phase 2**：预制体/场景 YAML 转换，生成 `_Prefabs/`、`_Scenes/`
- **Phase 6**：动画转换
- **Phase 7**：完整性验证

## 目录索引
- **文档**: `references/runbook.md` (流程), `references/scripts-index.md` (脚本参数).
- **映射**: `references/component-mapping.md` (组件), `references/api-mapping.md` (API).

## 坐标与尺寸转换约定
- **UI 节点**：保持像素单位（Pixels），不除以 PPU。`RectTransform` 的 `anchoredPosition` 和 `sizeDelta` 必须使用像素单位以配合 `CanvasScaler`。
- **世界节点**：除以 PPU（默认 100）转换为 Unity 世界单位。
- **锚点校准**：已修正 UI 节点的锚点与位置计算公式，确保 UGUI 布局与 Cocos 视觉一致。

## 已知修复与校准
- **SpriteMask**：补全了 Renderer 相关 Native 字段，解决迁移后 Mask 不生效问题。
- **UGUI 组件 GUID**：已校准 Unity 2022 版本的 UGUI 组件 GUID（Outline、Button、Slider 等），解决 Missing Script 问题。
- **UUID 编码**：Cocos UUID 为 Base64 变体，含 `+` 和 `/`，正则扫描需匹配完整字符集。

## 资源与目录清理
- **目录规范**: 统一存放于 `Assets/_Ported/` 下：`_Scenes` (场景), `_Prefabs` (预制体), `_Scripts` (代码), `_Textures` (纹理), `_Audio` (音频)。
- **冗余清理**: 迁移后需删除 `_res`, `Res`, `resources` 等原始路径下的非引用资源，仅保留 `manifest.json` 索引的有效资产。
- **孤立文件**: 定期清理 `.pac` (Cocos 自动图集中间件) 和 `.json` 冗余描述文件，Unity 使用 `SpriteAtlas` 替代。

