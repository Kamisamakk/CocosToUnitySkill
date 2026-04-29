using System;

/// <summary>
/// Singleton base class for Unity MonoBehaviour components.
/// Provides instance management similar to Cocos Creator's Singleton pattern.
/// </summary>
public class Singleton<T> where T : class, new()
{
    private static T _instance;
    private static readonly object _lock = new object();

    public static T instance()
    {
        if (_instance == null)
        {
            lock (_lock)
            {
                if (_instance == null)
                {
                    _instance = new T();
                    (_instance as Singleton<T>)?.OnCreate();
                }
            }
        }
        return _instance;
    }

    protected virtual void OnCreate() { }

    public static T Instance => instance();

    /// <summary>
    /// Check if instance exists without creating one.
    /// </summary>
    public static bool HasInstance() => _instance != null;

    /// <summary>
    /// Destroy the singleton instance. Call this in OnDestroy.
    /// </summary>
    protected static void DestroyInstance()
    {
        _instance = null;
    }
}
