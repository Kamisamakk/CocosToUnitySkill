# cocos-to-unity

**Cocos Creator (2.x / 3.x) → Unity** migration toolkit.

Agent-agnostic — works with Claude Code, Cursor, Windsurf, Cline, CodeBuddy, or standalone CLI.

---

## Features

A **6-phase automated pipeline** (Phase 0–5) to migrate a Cocos Creator game project to Unity:

| Phase | Script | Output |
|---|---|---|
| **0** — Audit | `audit_cocos_project.py` | JSON report: version, 2.x/3.x detection, asset inventory, risky APIs, Spine versions |
| **1** — Assets | `migrate_assets.py` | Unity assets + `.meta` + 9-slice + SpriteAtlas + UUID→GUID manifest |
| **2** — Scene/Prefab | `convert_prefab.py` | Batch convert ALL `.prefab`/`.scene`/`.fire` → Unity YAML |
| **3** — Scripts | `ts_to_csharp.py` | C# MonoBehaviour scaffolds from TS/JS |
| **4** — Anim/Spine/UI | `convert_anim.py` + manual | AnimationClip YAML + Spine/DragonBones hookup |
| **5** — Verify | `verify_migration.py` | Health score + orphan/TODO report |

### ⭐ Selective Migration (v2.7.0)

When you only need to port **one scene or prefab**, use `--target` to skip the full pipeline.
Only the target file and its transitive dependencies are migrated — saves massive time & tokens.

| Phase | What happens |
|---|---|
| A — Dependency Analysis | Deep-scan target JSON → collect all UUIDs, paths, nested prefabs |
| B — Selective Manifest | Build filtered manifest with only referenced assets |
| C — Copy Assets | Copy only referenced media + generate `.meta` stubs |
| D — Convert Target | Convert only the target scene/prefab → Unity YAML |

## Reference Docs (loaded on demand)

| File | Content |
|---|---|
| `references/changelog.md` | Version history (v2.0 → v2.7.0) |
| `references/scripts-index.md` | Script index + detailed CLI usage per phase |
| `references/troubleshooting.md` | Known pitfalls + quick troubleshooting table |
| `references/component-mapping.md` | cc.* ↔ Unity component table (40+ mappings) |
| `references/api-mapping.md` | cc.* ↔ UnityEngine.* API cheat sheet |
| `references/ui-mapping.md` | UI: Layout / Button / Label / ScrollView / Mask / Toggle |
| `references/asset-import-matrix.md` | Texture / audio / font / Spine / tilemap import defaults |
| `references/scene-pitfalls.md` | Coordinates, anchors, z-order, color inheritance, Widget→anchors |
| `references/spine-versions.md` | Spine version compatibility + DragonBones |
| `references/cocos-project-layout.md` | Cocos 2.x / 3.x directory structure + UUID system |
| `references/runbook.md` | Full phase-by-phase checklist |

## Quick Start

```bash
# Full pipeline — one command does everything
python scripts/pipeline.py --cocos /path/to/cocos-project --unity /path/to/unity-project

# With options
python scripts/pipeline.py --cocos /path/to/cocos-project --unity /path/to/unity-project \
  --atlas --convert-pos --ppu 100 --strict

# Single phase only
python scripts/pipeline.py --cocos /path/to/cocos-project --unity /path/to/unity-project --phase 0

# ⭐ Selective migration — only one scene + its dependencies
python scripts/pipeline.py --cocos /path/to/cocos-project --unity /path/to/unity-project \
  --target assets/scenes/MainMenu.scene
```

For individual script usage, see `references/scripts-index.md`.

## Known Limitations

- **Outline Component**: Migration of `cc.LabelOutline` to Unity's `UnityEngine.UI.Outline` is **temporarily disabled**. These components will be skipped during conversion to prevent potential scene corruption or "Missing Script" issues in complex projects.
- **Custom Materials**: Complex Cocos shaders/materials are not automatically converted.

## Cocos 2.x Support


The toolkit automatically detects Cocos 2.x projects:
- `.fire` scenes (different JSON schema from 3.x `.scene`)
- `cc.Class({})` JavaScript components (vs 3.x `@ccclass` TypeScript)
- 2.x coordinate system (bottom-left origin, clockwise rotation)
- 2.x UUID format (22-char compressed)
- Effort estimate auto-bumps for 2.x projects

## Requirements

- **Python 3.9+** (stdlib only, no pip install)
- **Unity 2020.3+** (any render pipeline)
- **Any OS**: Windows / macOS / Linux

## Installation

### As AI Agent Skill

Copy or symlink this folder to your agent's skill directory:

| Agent | Skill Path |
|---|---|
| CodeBuddy / WorkBuddy | `~/.workbuddy/skills/cocos-to-unity/` |
| Claude Code | `.claude/skills/cocos-to-unity/` or project root |
| Cursor | `.cursor/skills/cocos-to-unity/` |
| Generic | Any path; point the agent to `SKILL.md` |

### Standalone CLI

Just clone/copy the folder and run scripts directly with Python.

## License

MIT
