# Cocos → Unity Component Mapping

Trigger: `plan.json` contains `unity_component: null` entries, OR user asks how a specific `cc.*` component should be ported.

## UI

| Cocos                     | Unity                                    | Notes |
|---------------------------|-------------------------------------------|-------|
| `cc.UITransform`          | `RectTransform`                           | `contentSize` → sizeDelta; `anchorPoint` → pivot (recompute position) |
| `cc.Sprite`               | `UnityEngine.UI.Image`                    | `spriteFrame` → `sprite`; `type=SLICED` → Image.Type.Sliced |
| `cc.Label`                | `UnityEngine.UI.Text` (legacy)            | Prefer legacy `Text` unless TMP pkg already installed (memory: TMP broke ArrowsPuzzlee before) |
| `cc.RichText`             | `UnityEngine.UI.Text` + manual rich tags  | Cocos rich text BBCode ≠ Unity; parse manually |
| `cc.Button`               | `UnityEngine.UI.Button`                   | `clickEvents` → onClick listeners bound in code |
| `cc.EditBox`              | `UnityEngine.UI.InputField`               | `inputMode` maps roughly to `contentType` |
| `cc.Toggle`               | `UnityEngine.UI.Toggle`                   | `checkMark` → graphic |
| `cc.Slider`               | `UnityEngine.UI.Slider`                   | `progress` (0..1) → `value` within min/max |
| `cc.ScrollView`           | `UnityEngine.UI.ScrollRect`               | Content GameObject must exist as child |
| `cc.Layout`               | `HorizontalLayoutGroup` / `VerticalLayoutGroup` / `GridLayoutGroup` | Choose by `type`; `Cocos spacing` → UGUI `spacing` |
| `cc.Mask`                 | `UnityEngine.UI.Mask` or `RectMask2D`     | `RectMask2D` is cheaper; use for simple rect clipping |
| `cc.BlockInputEvents`    | `CanvasGroup`                             | Set `blocksRaycasts: true` and `ignoreParentGroups: false` |
| `cc.Widget`               | Anchor presets on `RectTransform`         | Rebuild via anchors; no direct component |


## Rendering

| Cocos                     | Unity                                    | Notes |
|---------------------------|-------------------------------------------|-------|
| `cc.Camera`               | `Camera`                                  | Cocos orthoHeight ≈ Unity camera.orthographicSize |
| `cc.Canvas`               | `Canvas` + `CanvasScaler`                 | `designResolution` → CanvasScaler `referenceResolution` |
| `cc.Sprite (simple)`      | `SpriteRenderer`                          | For non-UI sprites in 2D scene |
| `cc.ParticleSystem2D`     | `ParticleSystem`                          | Re-author; .plist particle configs are not auto-portable |
| `cc.Tiled*`               | Unity Tilemap (2D Tilemap Editor pkg)     | Manual rebuild; no automatic converter |

## Physics

| Cocos                     | Unity                                    | Notes |
|---------------------------|-------------------------------------------|-------|
| `cc.RigidBody2D`          | `Rigidbody2D`                             | `bodyType` maps: Static/Dynamic/Kinematic |
| `cc.BoxCollider2D`        | `BoxCollider2D`                           | `size`/`offset` 1:1 |
| `cc.CircleCollider2D`     | `CircleCollider2D`                        | `radius` 1:1 |
| `cc.PolygonCollider2D`    | `PolygonCollider2D`                       | `points` → `points` |
| `cc.PhysicsSystem2D`      | `Physics2D` (global)                      | Gravity set via `Physics2D.gravity` |

## Audio / Animation / Spine

| Cocos                     | Unity                                    | Notes |
|---------------------------|-------------------------------------------|-------|
| `cc.AudioSource`          | `AudioSource`                             | `clip` via manifest guid; `loop`, `volume` 1:1 |
| `cc.Animation`            | `Animator`                                | Clips must be regenerated via convert_anim.py |
| `sp.Skeleton`             | `Spine.Unity.SkeletonAnimation` (Spine-Unity pkg) | Runtime version must match Cocos's Spine version; see spine-versions.md |
| `dragonBones.ArmatureDisplay` | `DragonBones.UnityArmatureComponent`  | Requires DragonBones-Unity runtime |

## Scripts

Every `cc.Component` subclass becomes a `MonoBehaviour`. Use `ts_to_csharp.py`. Lifecycle:

| Cocos     | Unity       |
|-----------|-------------|
| onLoad    | Awake       |
| start     | Start       |
| update(dt)| Update      |
| lateUpdate| LateUpdate  |
| onEnable  | OnEnable    |
| onDisable | OnDisable   |
| onDestroy | OnDestroy   |

## Unmapped (handle manually)

`cc.SafeArea`, `cc.PageView`, `cc.VideoPlayer`, `cc.WebView`, `cc.MotionStreak`,
`cc.MeshRenderer` (3D), `cc.Light`, `cc.Skinning*` — no 1:1 Unity mapping;
replace with platform-appropriate solution or plugin.
