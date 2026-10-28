using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

namespace Kiwi.Desktop;

internal static class Program
{
    private const uint AttachParentProcess = 0xFFFFFFFF;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint processId);

    [STAThread]
    private static int Main(string[] args)
    {
        var options = LaunchOptions.Parse(args);
        AppPaths.EnsureDataDirs(options.DataDir);
        AppLog.Init(options.DataDir);

        if (options.SmokeTest)
        {
            AttachConsole(AttachParentProcess);
            try
            {
                return SmokeTest.RunAsync(options.DataDir).GetAwaiter().GetResult();
            }
            catch (Exception exception)
            {
                AppLog.Error("smoke-test 失败", exception);
                Console.Error.WriteLine(exception);
                return 1;
            }
        }

        ApplicationConfiguration.Initialize();

        using var instance = new SingleInstance();
        if (!instance.TryAcquire())
        {
            return 0;
        }

        if (!EnsureWebView2Runtime())
        {
            return 1;
        }

        // 宿主加入 kill-on-close Job；runtime、PostgreSQL、Qdrant 作为子进程继承，
        // 宿主崩溃时由内核统一清理。Job 创建失败不阻止启动，只记录日志。
        JobObject? job = null;
        try
        {
            job = new JobObject();
            job.AssignSelf();
        }
        catch (Exception exception)
        {
            AppLog.Warn($"Job Object 不可用，退出时可能残留子进程：{exception.Message}");
            job?.Dispose();
            job = null;
        }

        using (job)
        using (var form = new MainForm(options.DataDir))
        {
            instance.ActivationRequested += () =>
            {
                if (form.IsDisposed)
                {
                    return;
                }
                form.BeginInvoke(new Action(() =>
                {
                    if (form.WindowState == FormWindowState.Minimized)
                    {
                        form.WindowState = FormWindowState.Normal;
                    }
                    form.Show();
                    form.Activate();
                    form.BringToFront();
                }));
            };

            Application.Run(form);
        }
        return 0;
    }

    private static bool EnsureWebView2Runtime()
    {
        var fixedFolder = Directory.Exists(AppPaths.FixedWebView2Dir)
            ? AppPaths.FixedWebView2Dir
            : null;
        try
        {
            var version = CoreWebView2Environment.GetAvailableBrowserVersionString(fixedFolder);
            if (string.IsNullOrWhiteSpace(version))
            {
                throw new InvalidOperationException("WebView2 版本信息为空。");
            }
            AppLog.Info($"WebView2 运行时：{version}（来源：{(fixedFolder is null ? "系统" : "随包")}）");
            return true;
        }
        catch (Exception exception)
        {
            AppLog.Error("WebView2 运行时不可用", exception);
            var message = fixedFolder is null
                ? "未检测到 Microsoft Edge WebView2 运行时。\n\n"
                  + "请重新运行 Kiwi 安装包（安装器会自动安装 WebView2），\n"
                  + "或从微软官网下载并安装 WebView2 Runtime 后重试。"
                : $"无法加载随包的 WebView2 运行时：\n{fixedFolder}\n\n{exception.Message}";
            MessageBox.Show(
                message,
                "Kiwi 无法启动",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return false;
        }
    }

    private sealed class LaunchOptions
    {
        public string DataDir { get; private init; } = AppPaths.DefaultDataDir;

        public bool SmokeTest { get; private init; }

        public static LaunchOptions Parse(string[] args)
        {
            string? dataDir = null;
            var smokeTest = false;
            for (var index = 0; index < args.Length; index++)
            {
                switch (args[index])
                {
                    case "--data-dir" when index + 1 < args.Length:
                        dataDir = args[++index];
                        break;
                    case "--smoke-test":
                        smokeTest = true;
                        break;
                }
            }
            return new LaunchOptions
            {
                DataDir = AppPaths.ResolveDataDir(dataDir),
                SmokeTest = smokeTest,
            };
        }
    }
}
