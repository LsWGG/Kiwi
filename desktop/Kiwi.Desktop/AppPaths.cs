namespace Kiwi.Desktop;

/// <summary>安装目录与用户数据目录的唯一定义处。</summary>
internal static class AppPaths
{
    public static string BaseDir => AppContext.BaseDirectory;

    public static string RuntimeExe => Path.Combine(BaseDir, "runtime", "kiwi-runtime.exe");

    public static string ResourcesDir => Path.Combine(BaseDir, "resources");

    public static string FrontendDist => Path.Combine(ResourcesDir, "frontend");

    public static string FixedWebView2Dir => Path.Combine(BaseDir, "WebView2FixedRuntime");

    public static string DefaultDataDir => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Kiwi");

    public static string ResolveDataDir(string? overrideDir)
    {
        return string.IsNullOrWhiteSpace(overrideDir)
            ? DefaultDataDir
            : Path.GetFullPath(overrideDir);
    }

    public static string StateFile(string dataDir) => Path.Combine(dataDir, "runtime.json");

    public static string WebViewDataDir(string dataDir) => Path.Combine(dataDir, "WebView2");

    public static string WindowStateFile(string dataDir) => Path.Combine(dataDir, "window.json");

    public static string LogsDir(string dataDir) => Path.Combine(dataDir, "logs");

    public static string DesktopLog(string dataDir) => Path.Combine(LogsDir(dataDir), "desktop.log");

    public static string RuntimeLog(string dataDir) => Path.Combine(LogsDir(dataDir), "runtime.log");

    public static string EnsureDataDirs(string dataDir)
    {
        Directory.CreateDirectory(dataDir);
        Directory.CreateDirectory(LogsDir(dataDir));
        return dataDir;
    }
}
