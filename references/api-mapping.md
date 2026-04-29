# Cocos TypeScript API → Unity C# API

Trigger: `ts_to_csharp.py` leaves a `TODO(cocos2unity)` marker, or a `cc.*` call
is unfamiliar.

## Namespaces

| Cocos              | Unity                                       |
|--------------------|---------------------------------------------|
| `import { ... } from 'cc';` | `using UnityEngine;` + `using UnityEngine.UI;` |
| `cc.Node`          | `GameObject` (+ `Transform`)                |
| `cc.Component`     | `MonoBehaviour`                             |
| `cc.director`      | `UnityEngine.SceneManagement.SceneManager` (+ `Time`) |

## Common Calls

| Cocos                                      | Unity C#                                        |
|--------------------------------------------|-------------------------------------------------|
| `this.node`                                | `this.gameObject` / `this.transform`            |
| `this.node.active = true`                  | `this.gameObject.SetActive(true)`               |
| `this.node.getChildByName('X')`            | `transform.Find("X")?.gameObject`               |
| `this.node.addChild(child)`                | `child.transform.SetParent(this.transform, false)` |
| `this.node.destroy()`                      | `Destroy(this.gameObject)`                      |
| `this.getComponent(Label)`                 | `GetComponent<Text>()`                          |
| `this.node.on('click', cb, this)`          | `GetComponent<Button>().onClick.AddListener(cb)` |
| `cc.director.loadScene('Main')`            | `SceneManager.LoadScene("Main")`                |
| `cc.director.getScheduler().schedule(...)` | Coroutine (`IEnumerator` + `yield return new WaitForSeconds`) |
| `cc.resources.load('path/thing', Prefab)`  | `Resources.Load<GameObject>("path/thing")` (verify against manifest) |
| `cc.instantiate(prefab)`                   | `Instantiate(prefab)`                           |
| `cc.tween(node).to(1, {...}).start()`      | DOTween: `node.transform.DOMove(..., 1f)` — manual port |
| `console.log / warn / error`               | `Debug.Log / LogWarning / LogError`             |
| `cc.sys.platform`                          | `Application.platform`                          |
| `cc.sys.localStorage.setItem(k,v)`         | `PlayerPrefs.SetString(k, v); PlayerPrefs.Save()` |
| `cc.sys.localStorage.getItem(k)`           | `PlayerPrefs.GetString(k, defaultValue)`        |

## Math

| Cocos                  | Unity                               |
|------------------------|-------------------------------------|
| `new Vec3(x,y,z)`      | `new Vector3(x,y,z)`                |
| `new Vec2(x,y)`        | `new Vector2(x,y)`                  |
| `cc.Quat.fromEuler(...)` | `Quaternion.Euler(...)`           |
| `cc.Color`             | `Color32` / `Color`                 |

## Coroutines / Scheduling

```ts
// Cocos
this.scheduleOnce(() => { ... }, 1.0);
this.schedule(() => { ... }, 0.5);
```

```csharp
// Unity
Invoke(nameof(Fn), 1.0f);
InvokeRepeating(nameof(Fn), 0f, 0.5f);
// Or a coroutine:
StartCoroutine(DelayedCall());
IEnumerator DelayedCall() { yield return new WaitForSeconds(1f); ... }
```

## Event Bus

Cocos `EventTarget` has no 1:1 in Unity. Options:
- Simple: static C# events or `UnityEvent`.
- Scales better: a lightweight pub/sub class (10 lines), or install `UniRx` / `MessagePipe`.

## Asset References In Inspector

Cocos `@property(Prefab)` serialized field → C# `[SerializeField] private GameObject myPrefab;`. The reference must be rewired in Unity Inspector (manifest.json's UUID→GUID mapping is the ground truth when rebuilding scene YAML).
