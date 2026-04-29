# Known Pitfalls & Troubleshooting

## Known Pitfalls

| Issue | Detail | Mitigation |
|---|---|---|
| TMP compile errors | Importing TextMeshPro before package is installed → build breaks | Default to legacy `Text`; only use TMP when confirmed present |
| Coordinate handedness (3D) | Cocos 3D is right-handed (Z+forward); Unity is left-handed | Flip Z on all 3D positions and rotations |
| Anchor vs Pivot | Cocos `anchorPoint` ≈ Unity `RectTransform.pivot`, but position must be recomputed | See `references/scene-pitfalls.md` |
| Resources.load paths | Cocos `resources.load("path")` ≠ Unity `Resources.Load("path")` | Resolve via manifest.json, not string copy |
| Spine version lock | Skeleton export version must exactly match runtime | Detect from skeleton JSON `"spine"` field; see `references/spine-versions.md` |
| 2.x rotation sign | Cocos 2.x CW; Unity CCW | Negate rotation in convert_scene.py (auto) |
| 2.x anchor origin | 2.x default origin is bottom-left; 3.x is center | Auto-detected and offset applied |
| cc.Widget → anchors | No direct Unity component | Use `convert_widget.py` or check plan.json anchor data |
| 3.x objects missing `__uuid__` | SpriteFrame/Texture2D in scene JSON often lack `__uuid__` | Path-based reverse lookup via `_nativeUrl` (auto since v2.4.2) |
| 3.x `_N$field` naming | Some 3.x fields use `_N$fieldName` | All 3 variants tried automatically (since v2.4.2) |
| UNMAPPED fields empty in 3.x | Old filter `not k.startswith("_")` discarded all 3.x fields | Fixed with targeted exclusion list (v2.4.2) |
| SpriteFrame UUID missing | `.meta` subMetas UUIDs not in manifest | `find_all_cocos_uuids()` extracts all sub-asset UUIDs (v2.4.3) |
| Sprite reference silent fail | `_resolve_sprite_guid()` returned empty silently | stderr warnings added (v2.4.3) |
| Material `{fileID: 0}` | Components had no default material | Built-in defaults used (v2.4.4) |
| Camera `m_Iso` invalid | Unity doesn't recognize `m_Iso` | Fixed to `m_Orthographic` (v2.4.4) |
| SDK/ad residual refs | Scripts reference excluded SDK classes → compile errors | `--strip-sdk` auto-generates stubs; search for `[STUB]` in output and clean up |
| SDK dir false positive | Game-logic folder named "plugins" gets excluded | Add to `SdkFilter(custom_exclude_dirs=...)` allowlist or rename folder |
| Ad callback orphans | `onRewardedVideoComplete()` calls in game scripts after SDK strip | Search for `TODO(cocos2unity)` markers; replace with Unity Ads callbacks or remove |

## Quick Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Unity "GUID mismatch" warnings | manifest.json out of sync | Re-run `migrate_assets.py` |
| Sprites white/broken | Missing `.meta` or wrong textureType | Check `.meta` exists; verify `textureType: 8` |
| 9-slice looks wrong | Border not transferred | Check `border_9slice` in manifest; verify in Sprite Editor |
| Scripts don't compile | Missing `using` directive | Run verify; check `script_warnings` |
| Positions are huge | Pixel values not converted | Re-run with `--ppu 100` |
| Widget alignment lost | Widget not converted to anchors | Run `convert_widget.py` |
| Spine skeleton broken | Version mismatch | Check `spine_versions_detected` in audit |
| SDK compile errors after strip | Remaining refs to excluded SDK classes | Check for `[STUB]` .cs files; remove refs or implement Unity-native replacements |
| Too many files excluded | `--strip-sdk` keywords too aggressive | Customize `SdkFilter(extra_dir_keywords=...)` or check `sdk_excluded` in report.json |
