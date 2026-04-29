# Asset Import Matrix

Trigger: Phase 1 `migrate_assets.py` produces import warnings, or user reports texture/audio quality issues in Unity.

## Textures

| Source Format | Unity Importer | Default Settings | Notes |
|---|---|---|---|
| `.png` | TextureImporter | textureType=Sprite, sRGB=true, alphaIsTransparency=true, filterMode=Bilinear, ppu=100 | Standard for 2D games |
| `.jpg`/`.jpeg` | TextureImporter | Same but alphaIsTransparency=false | No alpha channel |
| `.webp` | TextureImporter | Same as PNG | Unity 2022.3+ supports webp natively |
| `.tga` | TextureImporter | Same as PNG | Lossless, larger file |
| `.bmp` | TextureImporter | Same as JPG | Rare in Cocos, consider converting |

### Sprite Atlas

Cocos auto-atlases at build time. Unity needs explicit **Sprite Atlas** assets:
1. After import, create `SpriteAtlas` assets per logical group (UI, characters, tiles).
2. Reference the atlas in scripts only when using `SpriteAtlas.GetSprite()`.
3. For simple projects, skip atlasing until performance profiling indicates need.

### Cocos SpriteFrame Trim

Cocos `.meta` stores `trimType`, `trimThreshold`, `borderTop/Bottom/Left/Right` for 9-slice.
- **9-slice**: set Unity `Sprite Editor → Border` (L/R/T/B pixels) matching Cocos values.
- **Trim**: Unity has `SpriteImportMode.Multiple` + auto-trim via Sprite Editor; usually ignore Cocos trim data.

## Audio

| Source Format | Unity Importer | Default Settings | Notes |
|---|---|---|---|
| `.wav` | AudioImporter | loadType=DecompressOnLoad, compressionFormat=PCM | Best for short SFX (<1s) |
| `.mp3` | AudioImporter | loadType=CompressedInMemory, compressionFormat=Vorbis, quality=1 | Good for BGM |
| `.ogg` | AudioImporter | Same as MP3 | Smaller; fully supported on all platforms |
| `.m4a` | AudioImporter | Same as MP3 | May need transcoding on some build targets |

### Optimization Tips

- SFX (< 200KB): `DecompressOnLoad` for lowest latency.
- BGM (> 500KB): `Streaming` for lowest memory.
- Mid-size: `CompressedInMemory` (default in our pipeline).

## Fonts

| Source | Unity Importer | Notes |
|---|---|---|
| `.ttf`/`.otf` | TrueTypeFontImporter | fontSize=16 default; Cocos uses dynamic rendering, Unity Font Asset also dynamic |
| `.fnt` (bitmap) | Not directly supported | Convert to SpriteFont or use TextMesh Pro's bitmap font tool |

### Cocos Label ↔ Unity Text font size

Cocos `fontSize` is in **design pixels**. Unity UI `Text.fontSize` is also in pixels but scaled by Canvas. Match by setting Canvas `referenceResolution` to Cocos `designResolution`.

## Spine / DragonBones

| File Set | Unity Package | Notes |
|---|---|---|
| `.json` + `.atlas` + `.png` (Spine) | `com.esotericsoftware.spine.spine-unity` | Version must match; see `spine-versions.md` |
| `.skel` + `.atlas` + `.png` (Spine binary) | Same | Binary skeleton; faster load |
| DragonBones `.json` + `.json` (skeleton+texture) + `.png` | DragonBones Unity Runtime | Download from dragonbones.com |

## Materials / Shaders

Cocos materials (`.mtl`) and effect files (`.effect`) have **no direct Unity equivalent**.
- Simple 2D sprites: Unity's default `Sprites-Default` shader suffices.
- Custom effects: rewrite as Unity ShaderLab / Shader Graph.
- `migrate_assets.py` copies `.effect` files but does NOT generate `.shader`; manual conversion required.

## Tiled Maps

Cocos `cc.TiledMap` loads `.tmx` + `.tsx`. Unity equivalent:
1. Install `2D Tilemap Editor` package.
2. Use `SuperTiled2Unity` (free asset) to import `.tmx` directly.
3. Or manual: create `Tilemap` + `TilemapRenderer`, paint tiles via Tile Palette.
