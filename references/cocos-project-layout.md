# Cocos Creator Project Layout

Trigger: Phase 0 `audit_cocos_project.py` encounters an unfamiliar directory layout.

## Cocos Creator 3.x (Standard)

```
<project-root>/
├── assets/                   # All game content
│   ├── resources/            # Dynamic-loaded assets (cc.resources.load)
│   ├── scenes/               # .scene files
│   ├── prefabs/              # .prefab files
│   ├── scripts/              # .ts TypeScript sources
│   ├── textures/             # Images (PNG/JPG)
│   ├── audio/                # Sound files
│   ├── animations/           # .anim clips
│   ├── spine/                # Spine .json/.atlas/.png
│   ├── fonts/                # .ttf/.otf/.fnt
│   └── ...                   # Custom folders
├── native/                   # Native platform configs (iOS/Android)
├── profiles/                 # Editor profiles
├── settings/                 # Project settings JSONs
├── temp/                     # Build cache (ignore)
├── library/                  # Import cache (ignore)
├── build/                    # Build output (ignore)
├── node_modules/             # npm deps (ignore)
├── package.json              # npm manifest + Creator version
├── project.json              # Legacy version marker (2.x leftover in some 3.x)
└── tsconfig.json             # TypeScript config
```

### Key Files

| File | Purpose |
|---|---|
| `package.json` → `creatorVersion` | Creator version string |
| `settings/v2/packages/scene.json` | Default scene, physics config |
| `settings/v2/packages/engine.json` | Render pipeline, physics module on/off |
| `assets/**/*.meta` | Per-file metadata: UUID, import settings, sub-assets |

### UUID System

Every file under `assets/` has a sibling `.meta` JSON containing a `uuid` (or `__uuid__`) field. This UUID is what scenes/prefabs use to reference assets. Our manifest maps these to Unity GUIDs.

Cocos 3.x UUID format: 36-char UUID with hyphens, or a shorter compressed form depending on Creator minor version.

## Cocos Creator 2.x (Legacy)

```
<project-root>/
├── assets/                   # Same role as 3.x
│   ├── resources/            
│   ├── Scene/                # .fire files (not .scene!)
│   └── Script/               # .js (not .ts by default)
├── library/
├── settings/
│   └── project.json          # Contains "engine-version"
├── packages/                 # Editor extensions
└── project.json              # Root-level; has no creatorVersion sometimes
```

### 2.x vs 3.x Differences

| Aspect | 2.x | 3.x |
|---|---|---|
| Scene format | `.fire` (different JSON schema) | `.scene` |
| Script language | JavaScript default, TS optional | TypeScript default |
| Component decorator | `cc.Class({extends: cc.Component, ...})` | `@ccclass` + `@property` |
| UUID format | 22-char compressed UUID | 36-char or compressed |
| Meta format | Flat JSON with `uuid`, `ver`, `subMetas` | Nested JSON, `__uuid__`, `importer` key |
| Coordinate system | Y-up, origin at bottom-left | Y-up, origin at center |

### Handling 2.x

The audit script detects 2.x by:
1. Presence of `.fire` files instead of `.scene`.
2. `engine-version` in `settings/project.json`.
3. `.js` scripts outnumber `.ts` scripts.

When 2.x is detected:
- `convert_scene.py` expects a different JSON structure and falls back to a 2.x parser branch.
- `ts_to_csharp.py` can still handle `.js` files but `cc.Class({})` style needs additional regex.
- Effort estimate bumps up one level (S→M, M→L).

## Ignored Directories

Never scan these:
- `temp/`, `library/`, `build/`, `node_modules/`, `.git/`, `local/`
