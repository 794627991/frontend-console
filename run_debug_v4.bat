@echo off
rem ============================================================
rem  V4 灰度调试启动器（harness 归一重构 batching）
rem  与 run_debug.bat 的唯一差别：额外 HARNESS_V4=1
rem   - 前端资源仍直读源码 web/（HARNESS_DEBUG_WEB=1）
rem   - 页面注入 window.__HG_V4__=true → v4main.on() 打开 v4 管线
rem  回旧管线：关掉本窗口，用 run_debug.bat 重开即可（开关是进程级）
rem ============================================================
cd /d "%~dp0"
set HARNESS_DEBUG_WEB=1
set HARNESS_V4=1
where python >nul 2>nul
if %errorlevel%==0 (
  python src\main.py
  pause
  exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (
  py src\main.py
  pause
  exit /b
)
echo Python not found
pause
