@echo off
rem ============================================================
rem  V4 debug launcher (harness v4 unified pipeline)
rem  Only diff vs run_debug.bat: extra HARNESS_V4=1
rem   - frontend still served from source web/ (HARNESS_DEBUG_WEB=1)
rem   - page injects window.__HG_V4__=true -> v4main.on() enables v4
rem  Back to old pipeline: close this window, run run_debug.bat
rem ============================================================
cd /d "%~dp0"
set HARNESS_DEBUG_WEB=1
set HARNESS_V4=1
where python >/dev/null 2>nul
if %errorlevel%==0 (
  python src\main.py
  pause
  exit /b
)
where py >/dev/null 2>nul
if %errorlevel%==0 (
  py src\main.py
  pause
  exit /b
)
echo Python not found
pause
