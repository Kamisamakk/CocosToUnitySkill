# Cocos → Unity Migration Runbook v2

Load this only when the user wants a printable, phase-by-phase checklist.

## Preconditions

- [ ] Cocos project builds and runs in its native editor before migration starts (capture a reference video/screenshots).
- [ ] Unity target version confirmed (default: 2022.3 LTS, Built-in RP, 2D Sprite).
- [ ] Python 3.9+ available on PATH (`python --version` or `python3 --version`).
- [ ] Source control: both Cocos and Unity projects committed to a clean branch.
- [ ] (Optional) `unity-plugin` (OpenClaw) installed and MCP Bridge running on port 27182.

## Phase 0 — Audit

- [ ] Run `audit_cocos_project.py --src <cocos-root> --out audit.json`.
- [ ] Check `creator_generation` field: if `2.x`, expect more manual work on scenes.
- [ ] Confirm Creator version; note if it's 2.x (`.fire`, `cc.Class`) or 3.x (`.scene`, `@ccclass`).
- [ ] Review `risky_api_counts`; flag Spine/DragonBones/tween/physics early.
- [ ] **Tween 检查**：若 `risky_api_counts` 显示使用 `cc.tween`，标记需导入 DOTween 插件。
- [ ] Check `spine_versions_detected` — record for Phase 4 Spine runtime install.

- [ ] Note `design_resolution` if present — needed for CanvasScaler setup.
- [ ] Review `script_stats.style_distribution` to understand 2.x vs 3.x script mix.
- [ ] Present effort estimate (S/M/L) to user and confirm scope.

## Phase 1 — Assets

- [ ] Create `Assets/_Ported/` staging folder in Unity.
- [ ] Run `migrate_assets.py --src <cocos>/assets --dst <unity>/Assets/_Ported --manifest manifest.json [--atlas]`.
- [ ] Check stats output: `errors` should be 0, `9slice` shows how many border sprites need verification.
- [ ] Open Unity; ensure no import errors in Console.
- [ ] If `has_9slice > 0`, spot-check a few sprites in Unity Sprite Editor → verify borders.
- [ ] Commit.

## Phase 2 — Scenes / Prefabs

For each scene and prefab (start with the simplest one):

- [ ] `convert_scene.py --src X.scene --manifest manifest.json --out plans/X.plan.json [--convert-pos]`.
- [ ] Check output: `format` shows detected version (2.x or 3.x).
- [ ] Review `unknown_components`; add entries to `COMPONENT_MAP` or resolve manually.
- [ ] Generate Unity Editor script: `apply_plan.py --plan plans/X.plan.json --out Assets/_Ported/Editor/ApplyPlan_X.cs [--ppu 100]`.
- [ ] (If many widgets) Generate widget script: `convert_widget.py --plan plans/X.plan.json --out Assets/_Ported/Editor/ApplyWidgets_X.cs`.
- [ ] In Unity: `Tools → Cocos2Unity → Apply Plan`, then `→ Apply Widgets` if applicable.
- [ ] Save as scene or prefab. Take screenshot, diff against Cocos reference.
- [ ] Commit.

## Phase 3 — 逻辑重写 (Scripts)

- [ ] **阅读源码**：针对每个脚本，先阅读 JS/TS 原文件，理解其核心功能和依赖。
- [ ] **准备插件**：若项目涉及 Tween 动画，向 Unity 工程导入 `assets/DOTween Pro.unitypackage`。
- [ ] **生成脚手架 (可选)**：运行 `ts_to_csharp.py --src <file>.ts` 仅作为字段和结构的参考。

- [ ] **人工编写 C#**：
  - [ ] 按照 `SKILL.md` 的规范从零开始手写 C# 代码。
  - [ ] 保持属性名称与 Cocos 一致，以便后续通过 `apply_plan.py` 或手动拖拽进行数据恢复。
  - [ ] 将 Cocos 专用 API 替换为 Unity 等效实现（参考 `references/api-mapping.md`）。
- [ ] **关联与绑定**：
  - [ ] 在 Unity 中将重写的脚本挂载回对应的 Prefab/Scene 节点。
  - [ ] **恢复引用**：参考 `plan.json` 或 Cocos 工程，手动将节点、图片、音效等引用拖入脚本插槽。
  - [ ] 如果使用 `apply_plan.py` 自动化恢复，确保 C# 字段名与原属性名精确匹配（不区分大小写，但建议完全一致）。
- [ ] **集成测试**：在 Unity 中检查编译错误，并确保核心逻辑能跑通。



## Phase 4 — Animation / Spine / Audio / UI

- [ ] `convert_anim.py` per clip; review sidecar `.notes.txt` for downgraded easings.
- [ ] Spine/DragonBones:
  - [ ] Check `spine_versions_detected` from Phase 0 audit.
  - [ ] Install matching spine-unity package (see `references/spine-versions.md`).
  - [ ] Wire `SkeletonAnimation` or `SkeletonGraphic` per prefab.
- [ ] Audio: verify `AudioSource.clip` references; test volume/loop.
- [ ] UI:
  - [ ] Set CanvasScaler `referenceResolution` to match Cocos `designResolution`.
  - [ ] Verify widget anchors applied correctly (check edges on different aspect ratios).
  - [ ] Verify 9-slice sprites render correctly at different sizes.
- [ ] Commit.

## Phase 5 — Verify & Cleanup

- [ ] `verify_migration.py --unity <unity-root> --manifest manifest.json --report report.md`.
- [ ] Check health score: aim for **PASS** or **REVIEW**.
- [ ] Resolve all `CRITICAL` issues (missing files, GUID mismatches).
- [ ] Resolve remaining TODOs; keep orphans intentionally only if user agrees.
- [ ] Check `script_warnings` — fix missing `using` directives.
- [ ] Optional: move `_Ported` contents into final folder structure; re-run verify.
- [ ] Tag a release commit, capture a final reference video, hand off report.

## Rollback

If Phase 2 or 3 produces unrecoverable scene/script state, revert the Unity branch
and re-run from the last passing phase. The manifest is the single source of truth
for asset identity; never hand-edit it.

## Quick Troubleshooting

| Problem | Quick Fix |
|---|---|
| Positions way off | Add `--ppu 100` to `apply_plan.py` or `--convert-pos` to `convert_scene.py` |
| White/broken sprites | Check `.meta` files exist; verify `textureType: 8` |
| Spine crash | Match `spine_versions_detected` with installed spine-unity package |
| Widget alignment wrong | Re-run `convert_widget.py`; compare with Cocos Widget Inspector |
| 2.x scripts fail | Check `ts_to_csharp.py` detected `2.x` style; verify `cc.Class` syntax |
