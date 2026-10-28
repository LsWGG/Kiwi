using System.Diagnostics;
using System.Globalization;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Kiwi.Desktop;

/// <summary>
/// 启动并监控 <c>runtime\kiwi-runtime.exe</c>。
///
/// 控制令牌由宿主随机生成，只通过子进程环境变量传入，不写入状态文件、
/// 命令行或日志。
/// </summary>
internal sealed class BackendRuntime : IDisposable
{
    public const string ControlTokenEnv = "KIWI_DESKTOP_CONTROL_TOKEN";

    private static readonly JsonSerializerOptions StateJson = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly string _dataDir;
    private readonly string _resourcesDir;
    private readonly string _frontendDist;
    private readonly string _stateFile;
    private readonly string _token;
    private Process? _process;
    private string? _baseUrl;

    public BackendRuntime(string dataDir, string resourcesDir, string frontendDist)
    {
        _dataDir = AppPaths.EnsureDataDirs(dataDir);
        _resourcesDir = resourcesDir;
        _frontendDist = frontendDist;
        _stateFile = AppPaths.StateFile(dataDir);
        _token = Convert.ToBase64String(RandomNumberGenerator.GetBytes(32))
            .Replace('+', '-')
            .Replace('/', '_')
            .TrimEnd('=');
    }

    public string? BaseUrl => _baseUrl;

    public string DataDir => _dataDir;

    public async Task StartAsync(IProgress<string>? progress, CancellationToken cancellationToken)
    {
        if (_process is { HasExited: false })
        {
            return;
        }
        if (!File.Exists(AppPaths.RuntimeExe))
        {
            throw new FileNotFoundException(
                "未找到 runtime\\kiwi-runtime.exe，请重新安装或先执行 desktop\\build.ps1。",
                AppPaths.RuntimeExe);
        }
        if (!File.Exists(Path.Combine(_frontendDist, "index.html")))
        {
            throw new DirectoryNotFoundException(
                $"前端资源缺失：{_frontendDist}；请重新安装应用。");
        }

        try
        {
            File.Delete(_stateFile);
        }
        catch (IOException)
        {
        }

        var info = new ProcessStartInfo
        {
            FileName = AppPaths.RuntimeExe,
            WorkingDirectory = AppPaths.BaseDir,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        info.ArgumentList.Add("--data-dir");
        info.ArgumentList.Add(_dataDir);
        info.ArgumentList.Add("--resources");
        info.ArgumentList.Add(_resourcesDir);
        info.ArgumentList.Add("--frontend-dist");
        info.ArgumentList.Add(_frontendDist);
        info.ArgumentList.Add("--state-file");
        info.ArgumentList.Add(_stateFile);
        info.ArgumentList.Add("--parent-pid");
        info.ArgumentList.Add(Environment.ProcessId.ToString(CultureInfo.InvariantCulture));
        info.ArgumentList.Add("--control-token-env");
        info.ArgumentList.Add(ControlTokenEnv);
        info.Environment[ControlTokenEnv] = _token;

        var process = new Process { StartInfo = info, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, e) =>
        {
            if (!string.IsNullOrEmpty(e.Data))
            {
                AppLog.Info($"runtime stdout: {e.Data}");
            }
        };
        process.ErrorDataReceived += (_, e) =>
        {
            if (!string.IsNullOrEmpty(e.Data))
            {
                AppLog.Warn($"runtime stderr: {e.Data}");
            }
        };

        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException("无法启动桌面 runtime。");
            }
        }
        catch (Exception exception)
        {
            process.Dispose();
            throw new InvalidOperationException($"无法启动桌面 runtime：{exception.Message}", exception);
        }
        _process = process;
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        AppLog.Info($"runtime 已启动，PID {process.Id}");

        var deadline = DateTime.UtcNow.AddSeconds(240);
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (process.HasExited)
            {
                throw new InvalidOperationException(
                    $"桌面 runtime 已退出（代码 {process.ExitCode}）。\n{TailRuntimeLog()}");
            }

            var state = ReadState();
            if (state?.Status == "error")
            {
                throw new InvalidOperationException(
                    $"桌面 runtime 启动失败（阶段：{state.Stage ?? "未知"}）：{state.Error}\n{TailRuntimeLog()}");
            }
            if (state?.Status == "ready" && state.HttpPort is int port && port > 0)
            {
                _baseUrl = $"http://127.0.0.1:{port}/";
                await WaitHealthyAsync(cancellationToken);
                progress?.Report("ready");
                return;
            }

            progress?.Report(state?.Stage ?? "boot");
            await Task.Delay(300, cancellationToken);
        }

        throw new TimeoutException($"桌面 runtime 在 240 秒内未就绪。\n{TailRuntimeLog()}");
    }

    private async Task WaitHealthyAsync(CancellationToken cancellationToken)
    {
        using var client = CreateClient(TimeSpan.FromSeconds(5));
        var deadline = DateTime.UtcNow.AddSeconds(45);
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                using var response = await client.GetAsync($"{_baseUrl}api/health", cancellationToken);
                if (response.IsSuccessStatusCode)
                {
                    return;
                }
            }
            catch (HttpRequestException)
            {
            }
            catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
            }
            await Task.Delay(300, cancellationToken);
        }
        throw new TimeoutException("后端健康检查超时，请查看 runtime.log。");
    }

    private RuntimeStateDto? ReadState()
    {
        try
        {
            var raw = File.ReadAllText(_stateFile);
            return JsonSerializer.Deserialize<RuntimeStateDto>(raw, StateJson);
        }
        catch (IOException)
        {
            return null;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private string TailRuntimeLog()
    {
        try
        {
            var path = AppPaths.RuntimeLog(_dataDir);
            if (!File.Exists(path))
            {
                return $"日志：{path}";
            }
            var lines = File.ReadAllLines(path);
            var tail = lines.Length <= 30 ? lines : lines[^30..];
            return $"日志：{path}\n{string.Join(Environment.NewLine, tail)}";
        }
        catch (IOException)
        {
            return $"日志：{AppPaths.RuntimeLog(_dataDir)}";
        }
    }

    /// <summary>请求内部关闭；超时后终止进程树（宿主自身在 Job 中，不能整体 Terminate）。</summary>
    public async Task StopAsync()
    {
        var process = _process;
        if (process is null)
        {
            return;
        }
        if (!process.HasExited && !string.IsNullOrEmpty(_baseUrl))
        {
            try
            {
                using var client = CreateClient(TimeSpan.FromSeconds(10));
                using var request = new HttpRequestMessage(
                    HttpMethod.Post, $"{_baseUrl}internal/shutdown");
                request.Headers.Add("x-kiwi-control-token", _token);
                using var response = await client.SendAsync(request);
                AppLog.Info($"已请求 runtime 关闭：HTTP {(int)response.StatusCode}");
            }
            catch (Exception exception)
            {
                AppLog.Warn($"内部关闭请求失败，将直接终止进程：{exception.Message}");
            }
        }

        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(25));
            await process.WaitForExitAsync(cts.Token);
            AppLog.Info("runtime 已退出");
        }
        catch (OperationCanceledException)
        {
            AppLog.Warn("runtime 未在 25 秒内退出，终止进程树");
            KillTree(process);
        }
        catch (InvalidOperationException)
        {
        }
    }

    private static void KillTree(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit(5000);
            }
        }
        catch (Exception exception)
        {
            AppLog.Error("终止 runtime 失败", exception);
        }
    }

    public void Dispose()
    {
        var process = _process;
        _process = null;
        if (process is null)
        {
            return;
        }
        if (!process.HasExited)
        {
            KillTree(process);
        }
        process.Dispose();
    }

    private static HttpClient CreateClient(TimeSpan timeout)
    {
        var handler = new HttpClientHandler
        {
            UseProxy = false,
            AllowAutoRedirect = false,
        };
        return new HttpClient(handler) { Timeout = timeout };
    }

    private sealed class RuntimeStateDto
    {
        [JsonPropertyName("status")]
        public string? Status { get; set; }

        [JsonPropertyName("stage")]
        public string? Stage { get; set; }

        [JsonPropertyName("http_port")]
        public int? HttpPort { get; set; }

        [JsonPropertyName("error")]
        public string? Error { get; set; }
    }
}
