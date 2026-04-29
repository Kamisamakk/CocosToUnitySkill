# Scene / Prefab Conversion Pitfalls

Trigger: Phase 2 `convert_scene.py` reports unknown components, or the rebuilt hierarchy looks wrong in Unity.

## 1. Coordinate Space

### 2D (Most common case)

Cocos 2D and Unity 2D are both Y-up, but:
- **Cocos origin**: center of the node (influenced by `anchorPoint`).
- **Unity origin**: pivot of `RectTransform` (for UI) or world origin for `Transform`.
- **Scale**: Cocos uses pixel units; Unity uses world units (1 unit = 100 pixels at default PPU).

**Fix**: Divide Cocos position values by `pixelsPerUnit` (default 100) when writing `transform.setPosition`. The `convert_scene.py` plan emits raw Cocos values; apply the conversion at batch execution time.

### 3D

Cocos 3D is **right-handed** (Z forward, Y up). Unity is **left-handed** (Z forward, Y up, but mirrored Z).
- Flip Z on all positions and rotations when porting 3D scenes.
- Most 2D games don't hit this.

## 2. Anchor / Pivot Mismatch

Cocos `cc.UITransform.anchorPoint` (0..1, 0..1) → Unity `RectTransform.pivot` (0..1, 0..1).

The semantics are the same, BUT:
- Cocos default anchor is `(0.5, 0.5)` (center).
- Unity default pivot is `(0.5, 0.5)` (center).
- When anchor differs from (0.5, 0.5), the position must be recomputed:

```
unity_pos.x = cocos_pos.x + (anchor.x - 0.5) * width
unity_pos.y = cocos_pos.y + (anchor.y - 0.5) * height
```

## 3. Z-Order / SortingOrder

Cocos uses `_localZOrder` + `setSiblingIndex()` for draw order.
Unity uses:
- **UI**: sibling order in hierarchy (later = on top).
- **SpriteRenderer**: `sortingOrder` + `sortingLayerName`.

**Fix**: sort children by `_localZOrder` before creating them in Unity so hierarchy order matches.

## 4. Color / Opacity Inheritance

Cocos nodes inherit parent's `_color` and `_opacity` by cascading them down.
Unity does NOT automatically cascade — each `Image`/`SpriteRenderer` has its own color.

**Fix**: if the Cocos tree uses parent opacity for fade effects, either:
- Set each child's alpha manually.
- Use a `CanvasGroup.alpha` on the parent (UI only).

## 5. Size vs Scale

Cocos `cc.UITransform.contentSize` defines the node's logical size in pixels.
Unity `RectTransform.sizeDelta` is similar but interacts with anchors.

When Cocos `contentSize` is set AND `scale` is not (1,1), just set `sizeDelta`.
When both `contentSize` and `scale` are non-default, apply both: `sizeDelta` for logical size, `localScale` for visual multiplier.

## 6. Missing Components

When `plan.json` flags `unity_component: null`:
1. Check `references/component-mapping.md` for the full table.
2. If the component is a custom `cc.Component` subclass (starts with a project-specific name, not `cc.`), it maps to a `MonoBehaviour` that `ts_to_csharp.py` should generate.
3. If it's a built-in component not yet in the map, add an entry to `COMPONENT_MAP` in `convert_scene.py` and rerun.

## 7. Prefab Nesting

Cocos prefabs can reference other prefabs via UUID. The conversion plan resolves these references via `manifest.json`, but:
- Convert leaf (non-nested) prefabs first.
- Then convert parent prefabs, instantiating child prefabs by their already-created Unity path.
- If a circular reference is detected (rare), break the cycle by converting one as a raw hierarchy.

## 8. Scene-Only vs Prefab-Only

A `.scene` contains world-level nodes (cameras, lights, canvas).
A `.prefab` is a single reusable subtree.

When converting scenes:
- Look for `cc.Canvas` → create Unity `Canvas` + `CanvasScaler` + `GraphicRaycaster`.
- Look for `cc.Camera` → ensure a Unity `Camera` exists (Unity scenes default to having one).

When converting prefabs:
- Do NOT create a Canvas or Camera unless the prefab explicitly contains one.

## 9. Widget → Anchors

Cocos `cc.Widget` defines edge alignment (top/bottom/left/right offsets + isAlignXxx flags).
Unity has no direct `Widget` component — the equivalent is `RectTransform` anchor presets + offsets.

Mapping:
| cc.Widget flag | Unity RectTransform |
|---|---|
| isAlignTop + isAlignBottom | anchorMin.y=0, anchorMax.y=1, offsetMin.y=bottom, offsetMax.y=-top |
| isAlignLeft + isAlignRight | anchorMin.x=0, anchorMax.x=1, offsetMin.x=left, offsetMax.x=-right |
| isAlignHorizontalCenter | anchorMin.x=0.5, anchorMax.x=0.5 |
| isAlignVerticalCenter | anchorMin.y=0.5, anchorMax.y=0.5 |

This is the single most tedious part of UI migration. Consider writing a helper script if the project has > 50 widgets.
