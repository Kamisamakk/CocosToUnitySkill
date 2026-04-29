# Changelog

## v2.7.1

- **Windows 中文路径支持**: 所有核心脚本 (`pipeline.py`, `convert_scene.py`, `convert_prefab.py`, `migrate_assets.py`, `selective_migrate.py`) 现在在 main() 入口自动设置 `sys.stdout.reconfigure(encoding="utf-8")`，确保中文路径名正确显示和处理。
- **Cocos 2.x 格式检测增强**: `detect_format()` 函数现在扫描所有对象（而非仅前 20 个），并检测更多 2.x 特征字段 (`_position`, `_scaleX`, `_scaleY`, `_contentSize`, `_anchorPoint`)，避免误判为 3.x。
- **2.x Transform 解析增强**:
  - `_position`, `_anchorPoint`, `_contentSize` 现在支持 `{__id__: N}` 引用解析（某些 Cocos 2.x 版本会使用引用）
  - 所有数值字段增加 `isinstance(val, (int, float))` 类型检查，避免意外的 `None` 或字符串值导致的错误
  - `_scaleX`, `_scaleY`, `_rotationX`, `_rotationY`, `_localZOrder` 等字段同样增强类型安全性
- **新增诊断脚本**: `debug_2x_scene.py` 用于分析 Cocos 2.x 场景 JSON 结构，帮助排查字段识别问题
- **测试**: transform 测试 10/10 ✅, selective_migrate 测试 15/15 ✅

## v2.7.0

- **Selective / single-scene migration (`--target`)**: New mode that migrates only one scene/prefab and its transitive dependencies, instead of the full 6-phase pipeline. Massive token and time savings for incremental migrations.
  - **New module `selective_migrate.py`** (~480 lines): Complete standalone implementation with 4-phase selective pipeline
  - **Phase A — Dependency Analysis**: `analyse_dependencies()` deep-scans target JSON to collect all `__uuid__`, `_uuid`, `uuid` fields, path hints (`_nativeUrl`, `_native`), nested prefab references, and custom `__type__` script names. Recursive walker with depth limit (30 levels).
  - **Phase B — Selective Manifest**: `build_selective_manifest()` scans all `.meta` files, builds UUID→file and path→UUID lookups, filters to only matching assets, registers sub-asset UUIDs (SpriteFrame→Texture) for correct Sprite reference chains.
  - **Phase C — Copy Assets**: `copy_selective_assets()` copies only referenced files to `Assets/_Ported/`, generates `.meta` stubs and folder `.meta` files. Supports `--dry-run`.
  - **Phase D — Convert Target**: `convert_selective_targets()` delegates to `convert_prefab.convert_single()` for each target file.
  - **Target resolution** with 4 fallback strategies: relative to project root, relative to assets/, absolute path, glob by filename.
  - **Pipeline integration**: `pipeline.py --target <path>` delegates entirely to `selective_migrate.py`.
  - **Compatible with existing flags**: `--strip-sdk`, `--ppu`, `--convert-pos`, `--dry-run`.
- **Test suite**: `test_selective_migrate.py` with 15 tests covering dependency analysis, selective manifest, copy behavior, and recursive reference collection.

## v2.6.0

- **SDK/ad/analytics stripping (`--strip-sdk`)**: New global pipeline flag that automatically excludes non-game content during migration:
  - **Phase 0 (Audit)**: Detects and reports SDK/ad/analytics/social/IAP/push/platform-bridge files with categorized summary in `report.json → sdk_excluded`
  - **Phase 1 (Migrate)**: Skips SDK assets entirely — directory-level pruning (never walks into SDK subtrees) + file-level filtering. Summary in `manifest.json → sdk_excluded_details`
  - **Phase 3 (Scripts)**: Pure SDK scripts get replaced with minimal stub `.cs` files (class name preserved to prevent compile errors from remaining references). Tainted scripts (game logic + SDK imports) get translated normally with SDK import lines commented out + `[STRIPPED]` markers
- **New shared module `sdk_filter.py`**: Centralized keyword database covering 70+ directory keywords, 50+ filename keywords, import/class regex patterns, and node-name patterns. Categories: `ad`, `sdk`, `analytics`, `social`, `iap`, `push`, `platform_bridge`
- **Extensible filter**: `SdkFilter(extra_dir_keywords=[...], custom_exclude_dirs=[...])` for project-specific overrides
- Per-script and individual CLI scripts also accept `--strip-sdk`

## v2.4.5

- **3.x rotation recovery from quaternion**: When `_euler` field is missing (some 3.x scenes only have `_lrot` quaternion), the tool now automatically converts the quaternion back to Euler angles via `_quat_to_euler()`. Previously this silently produced `[0,0,0]` rotation.
- **2.x anchor preservation on zero-size nodes**: Container nodes with `_contentSize: {width:0, height:0}` but non-center `_anchorPoint` now correctly generate an implicit UITransform with the pivot data. Previously the anchor was lost entirely.
- **2.x rotation _rotationX/_rotationY handling**: When `_rotationX ≠ _rotationY` (Cocos skew effect), the tool now averages them as a best-effort approximation instead of silently ignoring `_rotationY`.
- **Transform test suite**: New `test_transform.py` with 10 tests covering position, size, scale, rotation (euler/quaternion/roundtrip), anchor/pivot, Widget stretch/single-side, and non-UI Transform scenarios.

## v2.4.4

- **Parameter consistency across all 20+ component generators**: Every Cocos component property now has a corresponding Unity YAML field. Previously many parameters were hardcoded or ignored — now all are faithfully mapped from the Cocos source.
- **Default material fallback**: All `m_Material` fields now reference the correct Unity built-in default material instead of `{fileID: 0}`:
  - UI components (Image, Text, RawImage) → Unity Default UI Material (`fileID: 10754`)
  - SpriteRenderer → Unity Sprites-Default material
  - Custom materials from Cocos are resolved via the manifest; only missing ones fall back
- **Image component fill fixes**: `m_FillCenter` and `m_FillClockwise` were swapped — now correct. `fillStart` → `m_FillOrigin` mapping added (was hardcoded to 0).
- **Button SpriteState**: `normalSprite` / `pressedSprite` now resolved to Unity `m_SpriteState` fields (was completely missing). `duration` → `m_FadeDuration` now read from Cocos (was hardcoded 0.1).
- **Camera field corrections**: `m_Iso` (invalid) → `m_Orthographic` (correct Unity field name). `fov`, `near`, `far`, `rect` (viewport) now read from Cocos (were all hardcoded).
- **Slider reverse direction**: Cocos `reverse` flag now maps to Unity's 4 direction values (LeftToRight/RightToLeft/BottomToTop/TopToBottom).
- **ScrollRect inertia & movement type**: `inertia` inferred from `brake` value; `MovementType` from `elastic` field (was hardcoded to Elastic).
- **InputField enhancements**: `placeholder` text preserved as comment; `returnType` → `lineType` mapping; added `m_ReadOnly` field.
- **AudioSource pitch**: `pitch` field now mapped (was missing entirely).
- **Rigidbody2D constraints**: `fixedRotation` → `m_Constraints: 4` (FreezeRotation); `allowSleep` → `m_SleepingMode`.
- **SpriteRenderer flip & material**: `flipX` / `flipY` now read from Cocos (were hardcoded 0); `m_Material` references Sprites-Default.
- **LayoutGroup alignment**: `m_ChildAlignment` computed from Cocos `horizontalDirection` / `verticalDirection` (was hardcoded 0); `m_ReverseArrangement` set correctly.
- **Toggle interactable/transition**: Now reads from Cocos data (were hardcoded).
- **COMPONENT_MAP expanded**: 15 new fields across 9 components added to `convert_scene.py` for more complete property extraction.

## v2.4.3

- **SpriteFrame sub-asset UUID extraction (`find_all_cocos_uuids`)**: Cocos `.meta` files contain multiple UUIDs — the top-level Texture2D UUID and nested SpriteFrame UUIDs under `subMetas`. Previously only the primary UUID was recorded in the manifest, causing all Sprite references in scene JSON to fail silently. New `find_all_cocos_uuids()` function recursively extracts ALL UUIDs from `.meta` files (both 3.x hash-key format and 2.x sprite-name format).
- **Sub-asset UUID manifest registration**: `migrate_assets.py` now registers additional manifest entries for every sub-asset UUID (SpriteFrame, etc.), all mapping to the **same Unity GUID** as the parent texture. This is architecturally correct because Unity references Sprite sub-assets via `{fileID: 21300000, guid: <texture-guid>, type: 3}`.
- **`_resolve_sprite_guid()` diagnostic warnings**: `convert_prefab.py` now prints stderr warnings when encountering `_unresolved` asset references or UUIDs not found in the manifest, instead of silently returning empty string → `{fileID: 0}`.
- **End-to-end Sprite reference test (`test_sprite_ref.py`)**: 7-scenario regression test covering the complete chain from `.meta` UUID extraction through manifest registration to Unity YAML `m_Sprite` output.

## v2.4.2

- **Path-based reverse lookup for 3.x asset references**: When scene JSON objects lack `__uuid__` (common in 3.x), the resolver now recovers asset identity by matching `_nativeUrl`/`_native`/`_nativeAsset` path fields against manifest `src` paths via a `path_to_uuid` mapping table. This fixes the most common cause of "unresolved reference" in 3.x projects.
- **Recursion guard in `_deep_resolve_asset_ref()`**: Added `_visited` set to prevent infinite loops when objects cross-reference each other.
- **`_N$fieldName` naming convention support**: Cocos 3.x uses `_N$fieldName` for some component fields — now tried as a third naming variant alongside `fieldName` and `_fieldName`.
- **Fixed UNMAPPED component raw_fields being empty in 3.x**: The filter `not k.startswith("_")` discarded ALL 3.x fields (they all start with `_`). Now uses a targeted exclusion list (`__type__`, `__prefab__`, `__id__`, `_$`-prefix).
- **`cc.UIOpacity` → `CanvasGroup` mapping**: Cocos 3.x separates opacity into a dedicated component; now correctly mapped to Unity CanvasGroup with alpha conversion (0-255 → 0-1).
- **`cc.Graphics` and `cc.BlockInputEvents` in COMPONENT_MAP**: Added as known components (mapped to None with notes) to suppress "unmapped component" warnings.
- **Bonus asset reference scan**: After extracting mapped fields, all remaining component fields are scanned for `__id__`/`__uuid__` patterns and deep-resolved. This catches asset references on fields not listed in COMPONENT_MAP.
- **CanvasGroup YAML generator** (`convert_prefab.py`): New `_yaml_canvas_group()` function generates proper CanvasGroup serialized YAML from `cc.UIOpacity` component data.
- **End-to-end reference chain test** (`test_ref_chain.py`): Regression test covering 5 reference resolution scenarios (standard 3.x, path-based lookup, 2.x direct, compressed UUID, 3.x compressed).

## v2.4.1

- **GUID collision detection**: `migrate_assets.py` now validates all generated GUIDs against each other and against 11 known Unity built-in GUIDs.
- **Built-in GUID avoidance**: `stable_guid()` auto-avoids collisions with Unity built-in GUIDs via salt+rehash loop (up to 8 attempts).
- **`UNITY_BUILTIN_GUIDS` dictionary**: 11 known built-in GUIDs (Arial font, Extra resources, Default-Material, etc.) defined at module top level.
- **`validate_guid_collisions()` function**: Detects both internal entry collisions and built-in GUID collisions; returns collision records.
- **Manifest collision stats**: `migrate()` output now includes `guid_collisions` count; `main()` CLI shows collision count and stderr warning.

## v2.4.0

- **Deep asset reference resolution**: 3.x `{__id__: N}` references now recursively resolved through the scene/prefab JSON array, extracting `__uuid__` from cc.SpriteFrame, cc.TTFFont, cc.AudioClip, cc.AnimationClip, Spine data, DragonBones data
- **Font GUID resolution**: `_yaml_text()` now resolves font reference from plan.json via manifest; falls back to Arial only when no GUID found (was hardcoded Arial)
- **Animation clip GUID resolution**: `_yaml_animator()` now resolves defaultClip and all clips GUIDs; emits them as structured comments for AnimatorController creation
- **Spine SkeletonAnimation real fields**: `_yaml_spine()` generates real serialized fields (skeletonDataAsset GUID, initialSkinName, initialAnimation, initialLoop, premultipliedAlpha) instead of pure comments
- **DragonBones real fields**: `_yaml_dragonbones()` generates real serialized fields (unityDragonBonesData GUID, unityDragonBonesAtlasAsset GUID, armatureName, animationName, playTimes, timeScale) instead of pure comments
- **Node-level opacity → CanvasGroup**: Nodes with opacity < 255 auto-inject CanvasGroup component with correct alpha (UI nodes only)
- **Node-level color & layer extraction**: `build_plan_3x()` and `build_plan_2x()` now extract `_color`, `_opacity`, `_layer` at the node level into plan.json
- **DragonBones atlas asset**: Added `dragonAtlasAsset` and `playTimes`/`timeScale` to COMPONENT_MAP fields for full DragonBones data capture
- **ASSET_REF_FIELDS expanded**: Added `dragonAtlasAsset` for deep resolution of DragonBones atlas references
- **Custom script deep resolution**: Custom (user) script fields with `__id__` or `__uuid__` references are now deep-resolved too

## v2.3

- **Full property-level component mapping**: Scene/Prefab conversion now outputs real Unity serialized fields, not TODO comments
- **20+ component generators**: Image, Text, Button, Toggle, Slider, ScrollRect, InputField, Camera, SpriteRenderer, AudioSource, Animator, Rigidbody2D, BoxCollider2D, CircleCollider2D, PolygonCollider2D, LayoutGroups, RectMask2D, Spine, DragonBones
- **Color space auto-conversion**: Cocos (0-255 RGBA) → Unity (0-1 RGBA) for all color fields
- **m_Script GUID references**: 16 Unity built-in UI script GUIDs hardcoded for direct import without reassignment
- **Canvas auto-injects** CanvasScaler (with designResolution → referenceResolution mapping) + GraphicRaycaster
- **Sprite/Font/AudioClip** references resolved through manifest uuid→guid mapping
- **UI Layer auto-set**: Nodes with UI components automatically get m_Layer: 5
- **Widget → RectTransform** stretch mode properly computes offsetMin/offsetMax/sizeDelta
- **Cocos→Unity enum mapping**: TextAnchor, FontStyle, ImageType, FillMethod, CameraClearFlags, ButtonTransition, Rigidbody2D bodyType, InputField contentType
- **apply_plan.py** now accepts `--manifest` for YAML format asset reference resolution
- **Per-file fileID reset**: Deterministic YAML output across runs

## v2.2

- **`pipeline.py` unified entry point**: One command runs ALL 6 phases
- **Pure Python orchestration**: All phases call functions directly (no subprocess)
- **Per-phase execution**: `--phase N` to run any single phase independently
- **`convert_anim.py` batch mode**: `--src-dir` / `--dst-dir` for batch animation conversion
- **Pipeline timing**: Each phase reports elapsed time; total pipeline time at end
- **Smart manifest reuse**: Later phases auto-load manifest from earlier runs

## v2.1

- **Full asset migration**: ALL assets are migrated — no manual steps required
- **Native Unity prefabs**: Cocos `.prefab` → Unity `.prefab` YAML (auto batch)
- **Native Unity scenes**: Cocos `.scene` / `.fire` → Unity `.unity` YAML (auto batch)
- **convert_prefab.py**: New batch converter for all structural assets (prefab/scene)
- **apply_plan.py --format yaml**: Direct Unity YAML output, no more manual Editor menu
- **Smart asset routing**: `migrate_assets.py` now separates media from structural assets
- **Structural verification**: `verify_migration.py` tracks prefab/scene conversion completeness
- **6-phase pipeline**: Phase 2 now includes automatic prefab/scene conversion

## v2.0

- **Cocos 2.x support**: `.fire` scenes, `cc.Class({})` JS scripts, 2.x coordinate system
- **Auto-detection**: Automatically detects 2.x vs 3.x format and adapts parsing
- **9-slice borders**: Extracts border data from Cocos `.meta` and writes Unity sprite borders
- **Sprite Atlas generation**: Optional `--atlas` flag creates Unity SpriteAtlas per folder
- **Widget → Anchors**: `convert_widget.py` for batch anchor conversion
- **PPU conversion**: `--convert-pos` / `--ppu` flags for automatic pixel→world-unit conversion
- **Spine version detection**: Audit automatically finds Spine runtime versions in skeleton JSONs
