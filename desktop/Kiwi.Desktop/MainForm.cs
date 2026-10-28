using System.Drawing;
using System.Text;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Kiwi.Desktop;

/// <summary>
/// 主窗口：启动页 → WebView2 加载本机 SPA。
/// 所有非 loopback 的 HTTP(S) 请求、导航、弹窗与权限请求都会被拦截。
/// </summary>
internal sealed class MainForm : Form
{
    private readonly string _dataDir;
    private readonly string _windowStateFile;
    private readonly Panel _splash;
    private readonly Label _stageLabel;
    private readonly Label _errorLabel;
    private readonly Button _retryButton;
    private readonly Label _notice;
    private readonly System.Windows.Forms.Timer _noticeTimer;
    private readonly WebView2 _webView;

    private BackendRuntime? _runtime;
    private Uri? _origin;
    private Func<Task>? _retryAction;
    private bool _webViewReady;
    private bool _shutdownStarted;

    public MainForm(string dataDir)
    {
        _dataDir = dataDir;
        _windowStateFile = AppPaths.WindowStateFile(dataDir);

        Text = "Kiwi · 知识编译与检索";
        var appIcon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        if (appIcon is not null)
        {
            Icon = appIcon;
        }
        MinimumSize = new Size(1000, 700);
        AutoScaleMode = AutoScaleMode.Dpi;
        BackColor = Color.FromArgb(248, 250, 252);
        WindowStateStore.Apply(this, WindowStateStore.Load(_windowStateFile));

        _webView = new WebView2 { Dock = DockStyle.Fill, Visible = false };

        _notice = new Label
        {
            Dock = DockStyle.Fill,
            Height = 34,
            Visible = false,
            TextAlign = ContentAlignment.MiddleLeft,
            Padding = new Padding(14, 0, 14, 0),
            BackColor = Color.FromArgb(255, 247, 237),
            ForeColor = Color.FromArgb(180, 83, 9),
            Font = new Font("Segoe UI", 9.5f),
        };
        _noticeTimer = new System.Windows.Forms.Timer { Interval = 6000 };
        _noticeTimer.Tick += (_, _) =>
        {
            _noticeTimer.Stop();
            _notice.Visible = false;
        };

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 2,
            Margin = Padding.Empty,
            Padding = Padding.Empty,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.Controls.Add(_webView, 0, 0);
        layout.Controls.Add(_notice, 0, 1);

        _stageLabel = new Label
        {
            AutoSize = true,
            Text = "正在启动…",
            ForeColor = Color.FromArgb(71, 85, 105),
            Font = new Font("Segoe UI", 10.5f),
            Margin = new Padding(0, 10, 0, 10),
        };
        _errorLabel = new Label
        {
            AutoSize = true,
            MaximumSize = new Size(660, 0),
            Visible = false,
            ForeColor = Color.FromArgb(190, 18, 60),
            Font = new Font("Segoe UI", 9f),
        };
        _retryButton = new Button
        {
            Text = "重试",
            Visible = false,
            AutoSize = true,
            Margin = new Padding(0, 12, 0, 0),
            Padding = new Padding(18, 6, 18, 6),
        };
        _retryButton.Click += async (_, _) =>
        {
            var action = _retryAction;
            if (action is not null)
            {
                await action();
            }
        };

        var center = new FlowLayoutPanel
        {
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            FlowDirection = FlowDirection.TopDown,
            WrapContents = false,
            Anchor = AnchorStyles.None,
            MaximumSize = new Size(680, 0),
        };
        center.Controls.Add(new Label
        {
            AutoSize = true,
            Text = "Kiwi",
            Font = new Font("Segoe UI", 30f, FontStyle.Bold),
            ForeColor = Color.FromArgb(15, 23, 42),
            Margin = new Padding(0, 0, 0, 2),
        });
        center.Controls.Add(new Label
        {
            AutoSize = true,
            Text = "知识编译与检索",
            Font = new Font("Segoe UI", 12f),
            ForeColor = Color.FromArgb(100, 116, 139),
            Margin = new Padding(0, 0, 0, 18),
        });
        var progress = new ProgressBar
        {
            Style = ProgressBarStyle.Marquee,
            MarqueeAnimationSpeed = 28,
            Width = 360,
            Height = 4,
            Margin = new Padding(0, 0, 0, 12),
        };
        center.Controls.Add(progress);
        center.Controls.Add(_stageLabel);
        center.Controls.Add(_errorLabel);
        center.Controls.Add(_retryButton);

        var splashLayout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 1,
        };
        splashLayout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        splashLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        splashLayout.Controls.Add(center, 0, 0);

        _splash = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(248, 250, 252) };
        _splash.Controls.Add(splashLayout);

        Controls.Add(layout);
        Controls.Add(_splash);
        _splash.BringToFront();

        Shown += async (_, _) => await StartRuntimeAsync();
    }

    private async Task StartRuntimeAsync()
    {
        HideSplashError();
        _splash.Visible = true;
        _splash.BringToFront();
        _stageLabel.Text = StageText("boot");

        try
        {
            _runtime?.Dispose();
            _runtime = new BackendRuntime(_dataDir, AppPaths.ResourcesDir, AppPaths.FrontendDist);
            var progress = new Progress<string>(stage => _stageLabel.Text = StageText(stage));
            await _runtime.StartAsync(progress, CancellationToken.None);
            _stageLabel.Text = "正在加载界面…";
            await InitWebViewAsync();
        }
        catch (Exception exception)
        {
            AppLog.Error("桌面启动失败", exception);
            ShowSplashError(
                $"{exception.Message}\n\n日志：{AppPaths.LogsDir(_dataDir)}",
                StartRuntimeAsync);
        }
    }

    private async Task InitWebViewAsync()
    {
        var runtime = _runtime;
        if (runtime?.BaseUrl is null)
        {
            throw new InvalidOperationException("后端尚未就绪。");
        }
        _origin = new Uri(runtime.BaseUrl);

        if (_webViewReady)
        {
            _webView.Source = _origin;
            return;
        }

        var fixedRuntime = Directory.Exists(AppPaths.FixedWebView2Dir)
            ? AppPaths.FixedWebView2Dir
            : null;
        var options = new CoreWebView2EnvironmentOptions(WebViewPolicy.BrowserArguments);
        var environment = await CoreWebView2Environment.CreateAsync(
            fixedRuntime,
            AppPaths.WebViewDataDir(_dataDir),
            options);
        await _webView.EnsureCoreWebView2Async(environment);

        var core = _webView.CoreWebView2;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.AreHostObjectsAllowed = false;
        core.Settings.IsWebMessageEnabled = false;
        core.Settings.IsPasswordAutosaveEnabled = false;
        core.Settings.IsGeneralAutofillEnabled = false;
        core.Settings.AreDefaultScriptDialogsEnabled = true;

        core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += (_, e) => OnWebResourceRequested(environment, e);
        core.NavigationStarting += OnNavigationStarting;
        core.FrameNavigationStarting += OnFrameNavigationStarting;
        core.NewWindowRequested += (_, e) =>
        {
            e.Handled = true;
            ShowNotice("已阻止打开新窗口或外部链接。");
        };
        core.PermissionRequested += (_, e) =>
        {
            e.State = CoreWebView2PermissionState.Deny;
        };
        core.DownloadStarting += (_, e) =>
        {
            // 用户主动触发的本地导出（PDF / DOCX / 附件）允许下载。
            e.Cancel = false;
        };
        core.ProcessFailed += (_, e) =>
        {
            AppLog.Error($"WebView 进程异常：{e.ProcessFailedKind}");
            ShowSplashError("界面进程异常退出。可重试，或关闭后重新打开应用。", ReloadWebViewAsync);
        };
        core.NavigationCompleted += OnNavigationCompleted;

        _webViewReady = true;
        _webView.Visible = true;
        _webView.Source = _origin;
    }

    private void OnWebResourceRequested(
        CoreWebView2Environment environment,
        CoreWebView2WebResourceRequestedEventArgs e)
    {
        if (_origin is null)
        {
            e.Response = BlockedResponse(environment, "桌面版尚未就绪，已阻止网络请求。");
            return;
        }
        if (!Uri.TryCreate(e.Request.Uri, UriKind.Absolute, out var uri))
        {
            e.Response = BlockedResponse(environment, "已阻止无法识别的网络请求。");
            return;
        }
        if (!WebViewPolicy.IsAllowedRequest(uri, _origin))
        {
            AppLog.Warn($"已阻止外部请求：{uri.GetLeftPart(UriPartial.Path)}");
            e.Response = BlockedResponse(environment, $"桌面版已阻止外部网络请求：{uri.Host}");
        }
    }

    private static CoreWebView2WebResourceResponse BlockedResponse(
        CoreWebView2Environment environment,
        string message)
    {
        var body = new MemoryStream(Encoding.UTF8.GetBytes(message));
        return environment.CreateWebResourceResponse(
            body, 403, "Forbidden", "Content-Type: text/plain; charset=utf-8");
    }

    private void OnNavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs e)
    {
        if (_origin is null || !Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri))
        {
            return;
        }
        if (!WebViewPolicy.IsAllowedNavigation(uri, _origin))
        {
            e.Cancel = true;
            AppLog.Warn($"已阻止外部导航：{uri.Host}");
            ShowNotice($"已阻止打开外部链接：{uri.Host}。桌面版不访问外部网络。");
        }
    }

    private void OnFrameNavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs e)
    {
        if (_origin is null || !Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri))
        {
            return;
        }
        if (!WebViewPolicy.IsAllowedNavigation(uri, _origin))
        {
            e.Cancel = true;
            AppLog.Warn($"已阻止外部 iframe：{uri.Host}");
            ShowNotice("已阻止加载外部 iframe 内容。");
        }
    }

    private async void OnNavigationCompleted(object? sender, CoreWebView2NavigationCompletedEventArgs e)
    {
        if (!e.IsSuccess)
        {
            AppLog.Warn($"页面加载失败：{e.WebErrorStatus}");
            ShowSplashError(
                $"页面加载失败（{e.WebErrorStatus}）。请重试或查看日志：{AppPaths.LogsDir(_dataDir)}",
                ReloadWebViewAsync);
            return;
        }
        await Task.Yield();
        _splash.Visible = false;
    }

    private async Task ReloadWebViewAsync()
    {
        if (!_webViewReady || _runtime?.BaseUrl is null)
        {
            await StartRuntimeAsync();
            return;
        }
        HideSplashError();
        _splash.Visible = true;
        _splash.BringToFront();
        _stageLabel.Text = "正在重新加载界面…";
        _webView.Source = new Uri(_runtime.BaseUrl);
    }

    private void ShowSplashError(string message, Func<Task> retry)
    {
        _retryAction = retry;
        _errorLabel.Text = message;
        _errorLabel.Visible = true;
        _stageLabel.Text = "启动失败";
        _retryButton.Visible = true;
        _splash.Visible = true;
        _splash.BringToFront();
    }

    private void HideSplashError()
    {
        _errorLabel.Visible = false;
        _retryButton.Visible = false;
        _retryAction = null;
    }

    private void ShowNotice(string message)
    {
        _notice.Text = message;
        _notice.Visible = true;
        _noticeTimer.Stop();
        _noticeTimer.Start();
    }

    private static string StageText(string stage)
    {
        return stage switch
        {
            "boot" or "prepare" => "正在准备数据目录…",
            "postgres" => "正在启动 PostgreSQL…",
            "qdrant" => "正在启动向量库（可选）…",
            "migrate" => "正在升级数据库结构…",
            "http" => "正在启动后端服务…",
            "ready" => "正在加载界面…",
            "shutdown" => "正在退出…",
            _ => "正在启动…",
        };
    }

    protected override async void OnFormClosing(FormClosingEventArgs e)
    {
        if (_shutdownStarted)
        {
            base.OnFormClosing(e);
            return;
        }
        _shutdownStarted = true;
        e.Cancel = true;
        WindowStateStore.Save(_windowStateFile, this);
        try
        {
            _webView.Dispose();
        }
        catch (Exception exception)
        {
            AppLog.Warn($"释放 WebView 失败：{exception.Message}");
        }
        if (_runtime is not null)
        {
            await _runtime.StopAsync();
            _runtime.Dispose();
            _runtime = null;
        }
        BeginInvoke(new Action(Close));
    }
}
