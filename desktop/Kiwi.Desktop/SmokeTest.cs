using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;

namespace Kiwi.Desktop;

/// <summary>
/// 无窗口冒烟：启动 runtime，验证健康检查、SPA、深链接、桌面状态、笔记 CRUD、
/// 备份与内部关闭。结果同时写入 <c>logs\smoke-test.log</c>，退出码 0/1。
/// </summary>
internal static class SmokeTest
{
    public static async Task<int> RunAsync(string dataDir)
    {
        var results = new List<(bool Ok, string Line)>();
        var logPath = Path.Combine(AppPaths.LogsDir(dataDir), "smoke-test.log");

        void Record(string name, bool ok, string? detail = null)
        {
            var line = $"[{(ok ? "PASS" : "FAIL")}] {name}"
                + (string.IsNullOrEmpty(detail) ? string.Empty : $" — {detail}");
            results.Add((ok, line));
            Console.WriteLine(line);
        }

        AppLog.Info("smoke-test 开始");
        Record("runtime 存在", File.Exists(AppPaths.RuntimeExe), AppPaths.RuntimeExe);
        Record("前端资源存在", File.Exists(Path.Combine(AppPaths.FrontendDist, "index.html")), AppPaths.FrontendDist);

        using var runtime = new BackendRuntime(
            dataDir, AppPaths.ResourcesDir, AppPaths.FrontendDist);
        try
        {
            await runtime.StartAsync(null, CancellationToken.None);
            Record("runtime 就绪", true, runtime.BaseUrl);

            var baseUrl = runtime.BaseUrl!;
            using var handler = new HttpClientHandler { UseProxy = false };
            using var client = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(60) };

            using (var health = await client.GetAsync($"{baseUrl}api/health"))
            {
                Record("GET /api/health", health.IsSuccessStatusCode, ((int)health.StatusCode).ToString());
            }

            var index = await client.GetStringAsync(baseUrl);
            Record("GET / 返回 SPA", index.Contains("id=\"app\""), $"{index.Length} 字节");

            using (var request = new HttpRequestMessage(HttpMethod.Get, $"{baseUrl}settings/desktop"))
            {
                request.Headers.Accept.ParseAdd("text/html");
                using var response = await client.SendAsync(request);
                var body = await response.Content.ReadAsStringAsync();
                Record(
                    "深链接返回 SPA",
                    response.IsSuccessStatusCode && body.Contains("id=\"app\""),
                    ((int)response.StatusCode).ToString());
            }

            var status = await client.GetStringAsync($"{baseUrl}api/desktop/status");
            using (var document = JsonDocument.Parse(status))
            {
                Record(
                    "/api/desktop/status",
                    document.RootElement.TryGetProperty("desktop", out var desktop)
                        && desktop.GetBoolean(),
                    "desktop=true");
            }

            var kbId = await FirstKbIdAsync(client, baseUrl);
            if (kbId is null)
            {
                Record("创建 / 搜索笔记", false, "没有可用知识库");
            }
            else
            {
                var title = $"smoke-{DateTime.Now:yyyyMMddHHmmss}";
                var payload = JsonSerializer.Serialize(new
                {
                    title,
                    body_md = "Kiwi 桌面版冒烟测试正文。",
                });
                using var content = new StringContent(payload, Encoding.UTF8, "application/json");
                using var created = await client.PostAsync(
                    $"{baseUrl}api/notes?kb_id={Uri.EscapeDataString(kbId)}", content);
                Record(
                    "创建笔记",
                    created.StatusCode == HttpStatusCode.Created,
                    ((int)created.StatusCode).ToString());

                var search = await client.GetStringAsync(
                    $"{baseUrl}api/notes/search?kb_id={Uri.EscapeDataString(kbId)}"
                    + $"&q={Uri.EscapeDataString(title)}");
                Record("搜索笔记", search.Contains(title), $"{search.Length} 字节");
            }

            using (var backupClient = new HttpClient(handler, disposeHandler: false)
                   {
                       Timeout = TimeSpan.FromSeconds(240),
                   })
            {
                using var backup = await backupClient.PostAsync(
                    $"{baseUrl}api/maintenance/backups?sync=true", content: null);
                Record(
                    "同步备份",
                    (int)backup.StatusCode is 200 or 201 or 202,
                    ((int)backup.StatusCode).ToString());
            }

            await runtime.StopAsync();
            Record("内部关闭", true);
        }
        catch (Exception exception)
        {
            Record("smoke-test 异常", false, exception.Message);
            AppLog.Error("smoke-test 异常", exception);
        }
        finally
        {
            try
            {
                await runtime.StopAsync();
            }
            catch (Exception exception)
            {
                AppLog.Warn($"停止 runtime 失败：{exception.Message}");
            }
        }

        var summary = string.Join(Environment.NewLine, results.Select(item => item.Line));
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
            File.WriteAllText(logPath, summary + Environment.NewLine, Encoding.UTF8);
        }
        catch (IOException)
        {
        }
        Console.WriteLine(summary);
        return results.All(item => item.Ok) ? 0 : 1;
    }

    private static async Task<string?> FirstKbIdAsync(HttpClient client, string baseUrl)
    {
        try
        {
            var raw = await client.GetStringAsync($"{baseUrl}api/kbs");
            using var document = JsonDocument.Parse(raw);
            if (document.RootElement.ValueKind != JsonValueKind.Array)
            {
                return null;
            }
            foreach (var item in document.RootElement.EnumerateArray())
            {
                if (item.TryGetProperty("id", out var id))
                {
                    return id.GetString();
                }
            }
        }
        catch (Exception exception)
        {
            AppLog.Warn($"读取知识库列表失败：{exception.Message}");
        }
        return null;
    }
}
