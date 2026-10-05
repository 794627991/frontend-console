@echo off
rem DEBUG launcher: serves frontend DIRECTLY from source web/ dir.
rem Any code edit shows on refresh - no cache clearing needed.
rem First console line prints the served directory.
rem If port busy: close old app windows, run again.
cd /d "%~dp0"
set HARNESS_DEBUG_WEB=1
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
