using UnityEngine;
using System;
using System.Collections.Generic;

/// <summary>
/// Game Controller - Main game loop and global manager.
/// Translated from Cocos Creator GameController.ts
/// </summary>
public class GameController : MonoBehaviour
{
    public static GameController Instance { get; private set; }

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        DontDestroyOnLoad(gameObject);
    }

    private void Start()
    {
        // Initialize managers
        TaskManager.Instance.init();
        SysTaskManager.Instance.init();
    }

    private void Update()
    {
        float dt = Mathf.Min(Time.deltaTime, 0.1f);
        
        try
        {
            TaskManager.Instance.update2(dt);
            SysTaskManager.Instance.update2(dt);
        }
        catch (Exception e)
        {
            Debug.LogError($"Global timer exception: {e}");
        }

        try
        {
            BattleControl.Instance?.update2(dt);
            PoolManager.Instance?.update2(dt);
        }
        catch (Exception e)
        {
            Debug.LogError($"Battle timer exception: {e}");
        }
    }

    private void OnDestroy()
    {
        if (Instance == this)
        {
            Instance = null;
        }
    }
}
