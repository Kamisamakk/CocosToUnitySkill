using UnityEngine;
using System;
using System.Collections.Generic;

/// <summary>
/// Battle Control - Handles battle state and mini-game loading.
/// Translated from Cocos Creator BattleControl.ts
/// </summary>
public class BattleControl : Singleton<BattleControl>
{
    private bool _paused = false;
    public bool paused
    {
        get => _paused;
        set => _paused = value;
    }

    public float battleTime { get; private set; } = 0;
    private float _lastReportTime = 0;

    private Dictionary<string, bool> _loadFlags = new Dictionary<string, bool>();
    private Dictionary<string, MonoBehaviour> _miniGameCtrls = new Dictionary<string, MonoBehaviour>();

    public override void OnCreate() { }

    public void init() { }

    public void update2(float deltaTime)
    {
        if (_paused) return;

        deltaTime = Mathf.Min(deltaTime, 0.1f);
        battleTime += deltaTime;

        // Report every 60 seconds
        if (battleTime - _lastReportTime >= 60)
        {
            _lastReportTime = battleTime;
            // TODO: Implement reporting logic
        }
    }

    public void clearAll()
    {
        battleTime = 0;
        _lastReportTime = 0;
        _loadFlags.Clear();
        _miniGameCtrls.Clear();
    }

    /// <summary>
    /// Enter a mini-game by name and bundle path.
    /// </summary>
    public async void enterMiniGame(string gameName, string bundlePath)
    {
        if (!_loadFlags.ContainsKey(gameName) || _miniGameCtrls.ContainsKey(gameName))
        {
            // Statistics tracking
            // SmSdk.stat.cusEventOnce($"miniGameClickOnce_{gameName}");
            // SmSdk.stat.cusEvent($"miniGameClick_{gameName}");

            _loadFlags[gameName] = true;

            var ctrl = _miniGameCtrls[gameName];
            if (ctrl != null)
            {
                // Open loading panel then init
                await UIManager.Instance.open("LoadingPanel");
                ctrl.SendMessage("init");
            }
            else
            {
                // Load bundle and instantiate
                try
                {
                    // AssetBundle.LoadFromFileAsync or UnityWebRequest for bundle loading
                    // For now, use Resources as placeholder
                    string prefabPath = $"Prefabs/{gameName}_Ctrl";
                    var prefab = Resources.Load<GameObject>(prefabPath);
                    
                    if (prefab != null)
                    {
                        var instance = Instantiate(prefab, GameObject.Find("ItemHolder")?.transform);
                        var componentName = char.ToUpper(gameName[0]) + gameName.Substring(1) + "Ctrl";
                        
                        var miniCtrl = instance.GetComponent(componentName);
                        if (miniCtrl != null)
                        {
                            miniCtrl.SendMessage("init");
                            _miniGameCtrls[gameName] = miniCtrl;
                        }
                    }
                }
                catch (Exception e)
                {
                    Debug.LogError($"Load mini-game [{gameName}] error: {e}");
                    UIManager.Instance.tip("加载资源失败，请重启游戏");
                }
            }
        }
    }

    public void changeDirectorPaused()
    {
        if (Time.timeScale == 0)
            Time.timeScale = 1;
        else
            Time.timeScale = 0;
    }

    public void adCallBack()
    {
        foreach (var kvp in _miniGameCtrls)
        {
            kvp.Value?.SendMessage("adCallBack");
        }
    }
}
