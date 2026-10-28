using System.Drawing;
using System.Text.Json;
using System.Windows.Forms;

namespace Kiwi.Desktop;

/// <summary>记住窗口位置 / 大小 / 最大化状态；显示器变化时回退到默认尺寸。</summary>
internal static class WindowStateStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
    };

    public sealed class WindowState
    {
        public int X { get; set; }
        public int Y { get; set; }
        public int Width { get; set; } = 1440;
        public int Height { get; set; } = 900;
        public bool Maximized { get; set; }
    }

    public static WindowState Load(string path)
    {
        try
        {
            if (!File.Exists(path))
            {
                return new WindowState();
            }
            var state = JsonSerializer.Deserialize<WindowState>(File.ReadAllText(path), JsonOptions);
            return state ?? new WindowState();
        }
        catch (Exception)
        {
            return new WindowState();
        }
    }

    public static bool IsVisibleOnAnyScreen(Rectangle bounds)
    {
        return Screen.AllScreens.Any(screen => screen.WorkingArea.IntersectsWith(bounds));
    }

    public static void Save(string path, Form form)
    {
        var state = new WindowState
        {
            Maximized = form.WindowState == FormWindowState.Maximized,
            Width = form.RestoreBounds.Width,
            Height = form.RestoreBounds.Height,
            X = form.RestoreBounds.X,
            Y = form.RestoreBounds.Y,
        };
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, JsonSerializer.Serialize(state, JsonOptions));
        }
        catch (Exception exception)
        {
            AppLog.Warn($"保存窗口状态失败：{exception.Message}");
        }
    }

    public static void Apply(Form form, WindowState state)
    {
        form.StartPosition = FormStartPosition.Manual;
        var bounds = new Rectangle(state.X, state.Y, Math.Max(state.Width, 1000), Math.Max(state.Height, 700));
        if (IsVisibleOnAnyScreen(bounds))
        {
            form.Bounds = bounds;
        }
        else
        {
            var area = Screen.PrimaryScreen?.WorkingArea ?? new Rectangle(0, 0, 1440, 900);
            form.Size = new Size(Math.Min(1440, area.Width), Math.Min(900, area.Height));
            form.StartPosition = FormStartPosition.CenterScreen;
        }
        if (state.Maximized)
        {
            form.WindowState = FormWindowState.Maximized;
        }
    }
}
