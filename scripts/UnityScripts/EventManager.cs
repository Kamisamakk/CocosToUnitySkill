using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// Event Manager for decoupled event communication.
/// Translated from Cocos Creator EventManager.ts
/// </summary>
public class EventManager
{
    private Dictionary<string, List<System.Action<object>>> _eventMap = new Dictionary<string, List<System.Action<object>>>();
    private Dictionary<string, List<System.Action>> _eventMapNoArgs = new Dictionary<string, List<System.Action>>();

    private static EventManager _instance;
    public static EventManager Instance => _instance ?? (_instance = new EventManager());

    private EventManager() { }

    /// <summary>
    /// Register an event listener with data parameter.
    /// </summary>
    public void on(string eventName, System.Action<object> callback)
    {
        if (!_eventMap.ContainsKey(eventName))
        {
            _eventMap[eventName] = new List<System.Action<object>>();
        }
        if (!_eventMap[eventName].Contains(callback))
        {
            _eventMap[eventName].Add(callback);
        }
    }

    /// <summary>
    /// Register an event listener without parameters.
    /// </summary>
    public void on(string eventName, System.Action callback)
    {
        if (!_eventMapNoArgs.ContainsKey(eventName))
        {
            _eventMapNoArgs[eventName] = new List<System.Action>();
        }
        if (!_eventMapNoArgs[eventName].Contains(callback))
        {
            _eventMapNoArgs[eventName].Add(callback);
        }
    }

    /// <summary>
    /// Emit an event with data parameter.
    /// </summary>
    public void emit(string eventName, object data = null)
    {
        if (_eventMap.ContainsKey(eventName))
        {
            var callbacks = new List<System.Action<object>>(_eventMap[eventName]);
            foreach (var callback in callbacks)
            {
                try
                {
                    callback?.Invoke(data);
                }
                catch (System.Exception e)
                {
                    Debug.LogError($"Event callback error [{eventName}]: {e}");
                }
            }
        }
    }

    /// <summary>
    /// Emit an event without parameters.
    /// </summary>
    public void emit(string eventName)
    {
        if (_eventMapNoArgs.ContainsKey(eventName))
        {
            var callbacks = new List<System.Action>(_eventMapNoArgs[eventName]);
            foreach (var callback in callbacks)
            {
                try
                {
                    callback?.Invoke();
                }
                catch (System.Exception e)
                {
                    Debug.LogError($"Event callback error [{eventName}]: {e}");
                }
            }
        }
    }

    /// <summary>
    /// Remove a specific event listener.
    /// </summary>
    public void off(string eventName, System.Action<object> callback)
    {
        if (_eventMap.ContainsKey(eventName))
        {
            _eventMap[eventName].Remove(callback);
        }
    }

    /// <summary>
    /// Remove a specific event listener (no args).
    /// </summary>
    public void off(string eventName, System.Action callback)
    {
        if (_eventMapNoArgs.ContainsKey(eventName))
        {
            _eventMapNoArgs[eventName].Remove(callback);
        }
    }

    /// <summary>
    /// Remove all listeners for an event.
    /// </summary>
    public void offAll(string eventName)
    {
        _eventMap.Remove(eventName);
        _eventMapNoArgs.Remove(eventName);
    }

    /// <summary>
    /// Remove all event listeners.
    /// </summary>
    public void offAll()
    {
        _eventMap.Clear();
        _eventMapNoArgs.Clear();
    }

    /// <summary>
    /// Check if event has listeners.
    /// </summary>
    public bool has(string eventName)
    {
        return _eventMap.ContainsKey(eventName) || _eventMapNoArgs.ContainsKey(eventName);
    }

    /// <summary>
    /// Register one-time event listener.
    /// </summary>
    public void once(string eventName, System.Action<object> callback)
    {
        System.Action<object> wrappedCallback = null;
        wrappedCallback = (data) =>
        {
            off(eventName, wrappedCallback);
            callback?.Invoke(data);
        };
        on(eventName, wrappedCallback);
    }
}
