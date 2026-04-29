using UnityEngine;
using System;

/// <summary>
/// Task Manager for delayed and periodic task execution.
/// Translated from Cocos Creator SysTaskManager.ts
/// </summary>
public class SysTaskManager
{
    private static SysTaskManager _instance;
    public static SysTaskManager Instance => _instance ?? (_instance = new SysTaskManager());

    private class TaskItem
    {
        public Action callback;
        public float delay;
        public float interval;
        public int repeat;
        public float elapsed;
        public bool useUnscaledDeltaTime;
        public bool removed;
    }

    private System.Collections.Generic.List<TaskItem> _tasks = new System.Collections.Generic.List<TaskItem>();
    private System.Collections.Generic.List<TaskItem> _toAdd = new System.Collections.Generic.List<TaskItem>();
    private System.Collections.Generic.List<TaskItem> _toRemove = new System.Collections.Generic.List<TaskItem>();

    private SysTaskManager() { }

    /// <summary>
    /// Add a one-time delayed task.
    /// </summary>
    public void addTimeTask(Action callback, float delay, int repeat = 0, float interval = 0, bool useUnscaledDeltaTime = false)
    {
        TaskItem task = new TaskItem
        {
            callback = callback,
            delay = delay,
            repeat = repeat,
            interval = interval,
            elapsed = 0,
            useUnscaledDeltaTime = useUnscaledDeltaTime,
            removed = false
        };
        _toAdd.Add(task);
    }

    /// <summary>
    /// Add a repeating task.
    /// </summary>
    public void addRepeatTask(Action callback, float interval, int repeat = -1)
    {
        addTimeTask(callback, interval, repeat, interval);
    }

    /// <summary>
    /// Update loop - call this in your game's Update.
    /// </summary>
    public void update2(float deltaTime)
    {
        // Process additions
        foreach (var task in _toAdd)
        {
            _tasks.Add(task);
        }
        _toAdd.Clear();

        // Process tasks
        foreach (var task in _tasks)
        {
            if (task.removed) continue;

            float dt = task.useUnscaledDeltaTime ? Time.unscaledDeltaTime : deltaTime;
            task.elapsed += dt;

            if (task.elapsed >= task.delay)
            {
                try
                {
                    task.callback?.Invoke();
                }
                catch (Exception e)
                {
                    Debug.LogError($"Task execution error: {e}");
                }

                if (task.repeat == 0)
                {
                    task.removed = true;
                }
                else if (task.repeat > 0)
                {
                    task.repeat--;
                    if (task.repeat == 0)
                    {
                        task.removed = true;
                    }
                }

                task.elapsed = 0;
            }
        }

        // Process removals
        _tasks.RemoveAll(t => t.removed);
    }

    /// <summary>
    /// Remove all tasks.
    /// </summary>
    public void removeAll()
    {
        _tasks.Clear();
        _toAdd.Clear();
        _toRemove.Clear();
    }

    /// <summary>
    /// Get current task count.
    /// </summary>
    public int Count => _tasks.Count;
}
