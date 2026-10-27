# Windows 可行性 Spike 结果

- run: https://github.com/LsWGG/Kiwi/actions/runs/40510811416
- 生成时间: 2026-10-27T13:20:00+00:00

| 任务 | 作业结果 | 检查状态 | 说明 |
| --- | --- | --- | --- |
| pgserver | failure | 无结果 |  |
| qdrant | success | pass | Qdrant 1.20.0 Windows 二进制在 loopback 可用，读写与中文 payload 正常 |
| portable-python | failure | fail | Exception: D:\a\Kiwi\Kiwi\desktop\spike\check_portable_python.ps1:83 Line \|   83 \|      if ($LASTEXITCODE -ne 0) { throw "运行时探针退出码 $LASTEXITCODE" }      \|                     |
| pyinstaller | failure | fail | Exception: D:\a\Kiwi\Kiwi\desktop\spike\check_pyinstaller.ps1:71 Line \|   71 \|  …   if ($LASTEXITCODE -ne 0) { throw "冻结程序退出码 $LASTEXITCODE`n$output" }      \|                 |
| job-object | failure | pass | Job Object 可限制进程数 / 内存、终止进程树，KILL_ON_JOB_CLOSE 生效 |
| webview2 | success | pass | .NET 10 自包含发布成功，WebView2 运行时 155.0.4283.62 |
| backend-deps | failure | pass | 后端依赖在 Windows 安装成功，app.main 可导入 |
