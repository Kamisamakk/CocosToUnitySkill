using UnityEngine;
using System;
using System.Collections.Generic;

/// <summary>
/// Task Manager - Handles game-specific tasks and timing.
/// Translated from Cocos Creator TaskManager.ts
/// </summary>
public class TaskManager
{
    private static TaskManager _instance;
    public static TaskManager Instance => _instance ?? (_instance = new TaskManager());

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

    private TaskManager() { }

    public void init() { }

    /// <summary>
    /// Add a delayed task.
    /// </summary>
    public void addTimeTask(Action callback, float delay, int repeat = 0, float interval = 0)
    {
        TaskItem task = new TaskItem
        {
            callback = callback,
            delay = delay,
            repeat = repeat,
            interval = interval,
            elapsed = 0,
            useUnscaledDeltaTime = false,
            removed = false
        };
        _toAdd.Add(task);
    }

    /// <summary>
    /// Update loop.
    /// </summary>
    public void update2(float deltaTime)
    {
        // Process additions
        _tasks.AddRange(_toAdd);
        _toAdd.Clear();

        // Process tasks
        foreach (var task in _tasks)
        {
            if (task.removed) continue;

            task.elapsed += deltaTime;

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

        // Remove finished tasks
        _tasks.RemoveAll(t => t.removed);
    }

    /// <summary>
    /// Remove all tasks.
    /// </summary>
    public void removeAll()
    {
        _tasks.Clear();
        _toAdd.Clear();
    }

    public int Count => _tasks.Count;
}
