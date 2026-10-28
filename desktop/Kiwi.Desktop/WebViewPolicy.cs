namespace Kiwi.Desktop;

/// <summary>WebView2 的离线策略：只允许应用自身的 loopback origin。</summary>
internal static class WebViewPolicy
{
    /// <summary>
    /// Chromium 启动参数：关闭后台联网、组件更新、遥测与 hosts 解析。
    /// 真正的外联拦截仍在 WebResourceRequested 中完成，这里只是纵深防御。
    /// </summary>
    public const string BrowserArguments = string.Join(
        " ",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-breakpad",
        "--disable-client-side-phishing-detection",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-pings",
        "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost");

    public static bool IsLocalPreview(Uri uri)
    {
        return uri.Scheme is "blob" or "data" ||
               uri.AbsoluteUri is "about:blank" or "about:srcdoc";
    }

    /// <summary>仅允许与 <paramref name="origin"/> 完全一致的 http(s) 请求。</summary>
    public static bool IsAllowedRequest(Uri uri, Uri origin)
    {
        if (uri.Scheme is not ("http" or "https"))
        {
            // data: / blob: 由页面自身生成，不发起网络请求。
            return true;
        }
        return Uri.Compare(
            uri,
            origin,
            UriComponents.SchemeAndServer,
            UriFormat.Unescaped,
            StringComparison.OrdinalIgnoreCase) == 0;
    }

    /// <summary>导航只允许应用 origin、about:blank 与本地预览（blob / srcdoc）。</summary>
    public static bool IsAllowedNavigation(Uri uri, Uri origin)
    {
        if (IsLocalPreview(uri))
        {
            return true;
        }
        return IsAllowedRequest(uri, origin);
    }
}
