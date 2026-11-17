@echo off
rem DEBUG launcher: serves frontend DIRECTLY from source web/ dir.
rem Any code edit shows on refresh - no cache clearing needed.
rem First console line prints the served directory.
rem If port busy: close old app windows, run again.
rem
rem 无黑框（用户需求）：优先 pythonw（无控制台窗口），退回 pyw。
rem 原来用 python.exe，启动即弹一个 cmd 黑框；日志已改由进程内环形缓冲
rem 接管（src/backend_log.py），界面点版本号即可查看，不再需要黑框。
cd /d "%~dp0"
set HARNESS_DEBUG_WEB=1
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw.exe src\main.py
  exit /b
)
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw.exe src\main.py
  exit /b
)
rem 两者都没有才退回 python.exe（会有黑框，但先保证能起来）
where python >nul 2>nul
if %errorlevel%==0 (
  echo [warn] pythonw/pyw not found, falling back to python.exe (console window will show)
  python src\main.py
  pause
  exit /b
)
echo Python not found
pause
