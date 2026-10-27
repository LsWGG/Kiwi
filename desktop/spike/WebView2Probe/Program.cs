using System.Text.Encodings.Web;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Win32;

namespace WebView2Probe;

internal static class Program
{
    private const string RuntimeGuid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";

    [STAThread]
    private static int Main()
    {
        var result = new Dictionary<string, object?>
        {
            ["check"] = "webview2",
            ["status"] = "fail",
            ["details"] = new Dictionary<string, object?>(),
        };
        var details = (Dictionary<string, object?>)result["details"]!;
        try
        {
            details["dotnet"] = Environment.Version.ToString();
            details["os"] = Environment.OSVersion.ToString();
            details["process_arch"] = System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture.ToString();
            details["windows_forms"] = System.Windows.Forms.Application.ProductVersion;

            string? runtime = null;
            try
            {
                runtime = CoreWebView2Environment.GetAvailableBrowserVersionString();
            }
            catch (Exception ex)
            {
                details["get_version_error"] = $"{ex.GetType().Name}: {ex.Message}";
            }

            details["runtime_version"] = runtime;
            details["registry"] = ReadRegistry();

            if (string.IsNullOrEmpty(runtime))
            {
                throw new InvalidOperationException("未检测到 WebView2 Evergreen 运行时");
            }

            result["status"] = "pass";
            result["summary"] = $"WebView2 运行时可用：{runtime}";
        }
        catch (Exception ex)
        {
            result["error"] = ex.ToString();
        }
        finally
        {
            WriteResult(result);
        }

        return (string)result["status"]! == "pass" ? 0 : 1;
    }

    private static Dictionary<string, object?> ReadRegistry()
    {
        var found = new Dictionary<string, object?>();
        (string Name, RegistryKey Hive)[] hives =
        {
            ("HKCU", Registry.CurrentUser),
            ("HKLM", Registry.LocalMachine),
        };
        string[] paths =
        {
            $@"SOFTWARE\Microsoft\EdgeUpdate\Clients\{RuntimeGuid}",
            $@"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{RuntimeGuid}",
        };

        foreach (var (hiveName, hive) in hives)
        {
            foreach (var path in paths)
            {
                using var key = hive.OpenSubKey(path);
                var label = $@"{hiveName}\{path}";
                found[label] = key is null
                    ? null
                    : new Dictionary<string, object?>
                    {
                        ["pv"] = key.GetValue("pv")?.ToString(),
                        ["name"] = key.GetValue("name")?.ToString(),
                    };
            }
        }

        return found;
    }

    private static void WriteResult(Dictionary<string, object?> result)
    {
        var options = new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        };
        var json = JsonSerializer.Serialize(result, options);
        var path = Environment.GetEnvironmentVariable("SPIKE_OUT") ?? "desktop/spike/out/webview2.json";
        var full = Path.GetFullPath(path);
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        File.WriteAllText(full, json + Environment.NewLine);
        Console.WriteLine(json);
    }
}
