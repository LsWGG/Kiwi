# Windows 可行性 Spike 结果

- run: https://github.com/LsWGG/Kiwi/actions/runs/40530025776
- 生成时间: 2026-10-27T15:27:44+00:00

| 任务 | 作业结果 | 检查状态 | 说明 |
| --- | --- | --- | --- |
| pgserver | success | pass | pgserver 在 Windows 可用（ASCII 路径下启动、pg_dump、重启均通过）；非 ASCII 路径结果见 details.non_ascii_path |
| qdrant | success | pass | Qdrant 1.20.0 Windows 二进制在 loopback 可用，读写与中文 payload 正常 |
| portable-python | success | pass | 便携 Python 可运行 numpy / pandas / matplotlib / openpyxl / pillow |
| pyinstaller | success | pass | PyInstaller onedir 可冻结后端核心依赖并启动本地 HTTP 服务 |
| job-object | success | pass | Job Object 可限制进程数 / 内存、终止进程树，KILL_ON_JOB_CLOSE 生效 |
| webview2 | success | pass | .NET 10 自包含发布成功，WebView2 运行时 155.0.4283.62 |
| backend-deps | success | pass | 后端依赖在 Windows 安装成功，app.main 可导入 |
