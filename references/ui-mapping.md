# UI Component Mapping: Cocos → Unity

Trigger: Phase 4 UI rebuild, or user asks how a specific Cocos UI component maps to Unity UGUI.

## Layout Components

| Cocos `cc.Layout` type | Unity Equivalent | Key Properties |
|---|---|---|
| `HORIZONTAL` | `HorizontalLayoutGroup` | `spacing`, `childAlignment`, `padding` |
| `VERTICAL` | `VerticalLayoutGroup` | `spacing`, `childAlignment`, `padding` |
| `GRID` | `GridLayoutGroup` | `cellSize`, `spacing`, `constraint`, `startAxis` |
| `NONE` | No layout component | Children positioned manually |

### Cocos → Unity Property Map

| Cocos Property | Unity Property | Notes |
|---|---|---|
| `spacingX` | HLG/GLG `.spacing` | Horizontal gap |
| `spacingY` | VLG/GLG `.spacing` or GLG `.spacing.y` | Vertical gap |
| `paddingTop/Bottom/Left/Right` | `.padding` (RectOffset) | |
| `resizeMode = CONTAINER` | Content Size Fitter `horizontalFit/verticalFit = PreferredSize` | |
| `resizeMode = CHILDREN` | Layout Element with `preferredWidth/Height` | |
| `horizontalDirection = LEFT_TO_RIGHT` | `childAlignment = UpperLeft` + natural order | |
| `verticalDirection = TOP_TO_BOTTOM` | `childAlignment = UpperLeft` + reverse = false | |

## Button

| Cocos | Unity | Notes |
|---|---|---|
| `cc.Button.transition = COLOR` | `Button.transition = ColorTint` | Map `normalColor/pressedColor/hoverColor/disabledColor` |
| `cc.Button.transition = SPRITE` | `Button.transition = SpriteSwap` | Map `normalSprite/pressedSprite` |
| `cc.Button.transition = SCALE` | `Button.transition = Animation` | Create a simple scale animation or use `AnimationTriggers` |
| `cc.Button.clickEvents` | `Button.onClick` | Wire listeners in code: `btn.onClick.AddListener(Callback)` |
| `cc.Button.interactable` | `Button.interactable` | 1:1 |

## Label / Text

| Cocos `cc.Label` | Unity `Text` (legacy) | Notes |
|---|---|---|
| `string` | `text` | Content |
| `fontSize` | `fontSize` | Match if Canvas scaler matches designResolution |
| `fontFamily` / `font` (asset) | `font` | Wire via manifest GUID |
| `lineHeight` | `lineSpacing` | Unity uses a multiplier (1.0 = default); Cocos uses pixels |
| `horizontalAlign` | `alignment` | LEFT/CENTER/RIGHT map to TextAnchor |
| `verticalAlign` | `alignment` | TOP/MIDDLE/BOTTOM combined with horizontal |
| `overflow = CLAMP` | Set `horizontalOverflow = Wrap`, `verticalOverflow = Truncate` | |
| `overflow = SHRINK` | `bestFit = true` | Unity auto-shrinks |
| `overflow = RESIZE_HEIGHT` | Add `ContentSizeFitter` verticalFit=PreferredSize | |
| `color` | `color` | RGBA direct map |
| `enableBold / enableItalic / enableUnderline` | Use `<b>`, `<i>` rich text tags or `fontStyle` | |

## ScrollView

| Cocos `cc.ScrollView` | Unity `ScrollRect` | Notes |
|---|---|---|
| `content` (node ref) | `content` (RectTransform ref) | Must be a child |
| `horizontal` | `horizontal` | bool |
| `vertical` | `vertical` | bool |
| `brake` (0..1) | `decelerationRate` | Cocos 0 = no brake; Unity 0.135 default. Approximate: `decelerationRate = 1 - brake * 0.9` |
| `bounceDuration` | `elasticity` | Cocos in seconds; Unity is a factor (0.1 default). Rough: `elasticity = bounceDuration * 10` |
| `scrollBarEnabled` | Add `Scrollbar` child + wire | Not automatic in Unity |

## Mask

| Cocos `cc.Mask` type | Unity | Notes |
|---|---|---|
| `RECT` | `RectMask2D` | Cheapest option |
| `ELLIPSE` | `Mask` + circular sprite | Requires a white circle sprite as `Image.sprite` |
| `GRAPHICS_STENCIL` | `Mask` component | Set `showMaskGraphic = false` for invisible mask |

## Sprite

| Cocos `cc.Sprite` property | Unity `Image` property | Notes |
|---|---|---|
| `spriteFrame` (asset ref) | `sprite` | Resolve via manifest |
| `type = SIMPLE` | `Image.Type = Simple` | |
| `type = SLICED` | `Image.Type = Sliced` | Must set sprite borders in Sprite Editor |
| `type = TILED` | `Image.Type = Tiled` | |
| `type = FILLED` | `Image.Type = Filled` | Map `fillType`, `fillCenter`, `fillStart`, `fillRange` |
| `sizeMode = CUSTOM` | Set `rectTransform.sizeDelta` manually | |
| `sizeMode = TRIMMED` | `Image.SetNativeSize()` then adjust | |
| `color` | `color` | RGBA |
| `trim` | N/A | Unity sprites auto-trim in Sprite Editor |

## Toggle / ToggleGroup

| Cocos | Unity | Notes |
|---|---|---|
| `cc.Toggle.isChecked` | `Toggle.isOn` | |
| `cc.Toggle.checkMark` (sprite node) | `Toggle.graphic` | Assign the checkmark Image |
| `cc.ToggleContainer` (parent) | `ToggleGroup` | Add to parent; wire each Toggle's `group` field |
| `allowSwitchOff` | `ToggleGroup.allowSwitchOff` | 1:1 |

## EditBox / InputField

| Cocos `cc.EditBox` | Unity `InputField` | Notes |
|---|---|---|
| `string` | `text` | |
| `placeholder` | `placeholder.text` | Unity uses a child Text as placeholder |
| `maxLength` | `characterLimit` | |
| `inputMode = ANY` | `contentType = Standard` | |
| `inputMode = NUMERIC` | `contentType = IntegerNumber` or `DecimalNumber` | |
| `inputMode = EMAIL_ADDR` | `contentType = EmailAddress` | |
| `inputFlag = PASSWORD` | `contentType = Password` | |

## ProgressBar / Slider

| Cocos `cc.ProgressBar` | Unity `Slider` | Notes |
|---|---|---|
| `progress` (0..1) | `value` (within min=0, max=1) | |
| `mode = HORIZONTAL` | `direction = LeftToRight` | |
| `mode = VERTICAL` | `direction = BottomToTop` | |
| `barSprite` | `fillRect` | Wire the fill Image's RectTransform |
| `totalLength` | sizeDelta of the slider rect | |
