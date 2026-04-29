# Spine Runtime Version Compatibility

Trigger: Phase 4, Spine skeleton import fails or animations play incorrectly.

## The Golden Rule

> The Spine runtime version used in Unity MUST exactly match the Spine editor version used to export the skeleton data. A mismatch → broken bones, missing animations, or crash.

## Version Matrix

| Spine Editor | Cocos Spine Runtime | Unity spine-unity Package | Notes |
|---|---|---|---|
| 3.6.x | spine-cocos2dx 3.6.x | spine-unity 3.6.x | Project memory: ArrowsPuzzlee uses 3.6.52 |
| 3.7.x | spine-cocos2dx 3.7.x | spine-unity 3.7.x | |
| 3.8.x | spine-ts 3.8.x (Cocos Creator) | spine-unity 3.8.x | |
| 4.0.x | spine-ts 4.0.x | spine-unity 4.0.x | Major skeleton format change |
| 4.1.x | spine-ts 4.1.x | spine-unity 4.1.x | |
| 4.2.x | spine-ts 4.2.x | spine-unity 4.2.x | Latest stable as of 2024 |

## How To Detect Spine Version

### From Cocos project

1. Check `package.json` or `npm` dependencies for `spine-cocos` / `@esotericsoftware/spine-core` version.
2. Check `.json` skeleton files: the `"spine"` field at the top level contains the version string.

```json
{
  "skeleton": { "spine": "3.6.52", "width": 200, "height": 400 },
  ...
}
```

3. Binary `.skel` files: the first bytes contain the version string (not easily readable without a parser).

### Recommended approach

```python
import json
data = json.load(open("skeleton.json"))
print(data.get("skeleton", {}).get("spine", "unknown"))
```

## Installing spine-unity in Unity

### Via Unity Package Manager (UPM)

For Spine 4.x:
```
# manifest.json in Packages/
"com.esotericsoftware.spine.spine-csharp": "https://github.com/EsotericSoftware/spine-runtimes.git?path=spine-csharp/src#4.2",
"com.esotericsoftware.spine.spine-unity": "https://github.com/EsotericSoftware/spine-runtimes.git?path=spine-unity/Assets/Spine#4.2"
```

For Spine 3.6/3.7/3.8:
- No UPM support. Download the `.unitypackage` from [Spine downloads archive](http://esotericsoftware.com/spine-unity-download).
- Import via `Assets → Import Package → Custom Package`.

### Via unity-plugin (OpenClaw)

```
unity_execute: package.add {gitUrl: "https://github.com/EsotericSoftware/spine-runtimes.git?path=spine-unity/Assets/Spine#4.2"}
```

## Component Mapping

| Cocos | Unity | Notes |
|---|---|---|
| `sp.Skeleton` component on a Node | `SkeletonAnimation` on a GameObject (world-space) | For non-UI skeletons |
| `sp.Skeleton` inside Canvas | `SkeletonGraphic` on a GameObject (Canvas child) | For UI-embedded skeletons |

### SkeletonAnimation setup

```
unity_execute: gameobject.create {name: "MySpine"}
unity_execute: component.add {name: "MySpine", componentType: "Spine.Unity.SkeletonAnimation"}
unity_execute: component.set {name: "MySpine", componentType: "Spine.Unity.SkeletonAnimation", fieldName: "skeletonDataAsset", value: "<GUID from manifest>"}
```

### SkeletonGraphic setup

Same as above but use `Spine.Unity.SkeletonGraphic`. Also requires an `Image` or `RawImage` sibling? No — `SkeletonGraphic` renders itself on the Canvas.

## DragonBones

DragonBones is less common than Spine and has its own Unity runtime:
- GitHub: [DragonBones/DragonBonesCSharp](https://github.com/DragonBones/DragonBonesCSharp)
- Import as a `.unitypackage` or copy the `DragonBones/` folder into Assets.

Component: `DragonBones.UnityArmatureComponent`

Version compatibility is simpler — DragonBones format is more stable across minor versions. Just match major version (5.x → 5.x runtime).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `SkeletonDataAsset failed to load` | Version mismatch | Check skeleton JSON `"spine"` field vs runtime version |
| Bones in wrong position | 3.x skeleton loaded in 4.x runtime | Downgrade runtime or re-export from Spine editor |
| Animations don't play | Animation name mismatch | Cocos may prefix/postfix anim names; check `state.SetAnimation` calls |
| Transparent skeleton | Atlas texture not found | Ensure `.atlas` + `.png` sit next to `.json`; reimport |
| Clipping not working | ClippingAttachment needs mesh | Ensure `Advanced - Solve Tangents` is off; enable Clipping in SkeletonAnimation inspector |
