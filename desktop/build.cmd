@echo off
rem Kiwi Windows 桌面版打包入口（双击或命令行）。
rem 用法： desktop\build.cmd -Version 1.0.0
rem 所有参数原样传给 build.ps1；失败时暂停，便于查看日志。

setlocal
set "SCRIPT=%~dp0build.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo [Kiwi] 构建失败，退出码 %CODE%。
    echo 详情见上方输出与 desktop\build\ 下的日志。
    pause
)
exit /b %CODE%
