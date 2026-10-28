using System.Text;

namespace Kiwi.Desktop;

/// <summary>宿主日志：写入 <c>%LOCALAPPDATA%\Kiwi\logs\desktop.log</c>，永不记录控制令牌。</summary>
internal static class AppLog
{
    private static readonly object Gate = new();
    private static string? _path;

    public static void Init(string dataDir)
    {
        AppPaths.EnsureDataDirs(dataDir);
        _path = AppPaths.DesktopLog(dataDir);
    }

    public static void Info(string message) => Write("INFO", message);

    public static void Warn(string message) => Write("WARN", message);

    public static void Error(string message, Exception? exception = null)
    {
        Write("ERROR", exception is null ? message : $"{message}: {exception}");
    }

    private static void Write(string level, string message)
    {
        var path = _path;
        var line = $"{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss.fff zzz} [{level}] {message}{Environment.NewLine}";
        if (path is null)
        {
            return;
        }
        try
        {
            lock (Gate)
            {
                File.AppendAllText(path, line, Encoding.UTF8);
            }
        }
        catch (IOException)
        {
            // 日志写入失败不能影响启动或退出。
        }
        catch (UnauthorizedAccessException)
        {
        }
    }
}
