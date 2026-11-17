@echo off
rem DEBUG launcher: serves frontend DIRECTLY from source web/ dir.
rem Any code edit shows on refresh - no cache clearing needed.
rem First console line prints the served directory.
rem If port busy: close old app windows, run again.
rem
rem No console window (user request): prefer pythonw, fall back to pyw.
rem Was python.exe which popped a cmd box; logs now go to the in-process
rem ring buffer (src/backend_log.py), click the version badge to view.
rem
rem NOTE: keep this file ASCII-only. cmd.exe parses .bat in the OEM codepage
rem (GBK here), so UTF-8 Chinese comments get split mid-byte and the stray
rem bytes escape the "rem" prefix and run as commands ("'nsole' is not
rem recognized...").
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
rem Neither found: fall back to python.exe (console window shows, but at least runs)
where python >nul 2>nul
if %errorlevel%==0 (
  echo [warn] pythonw/pyw not found, falling back to python.exe
  python src\main.py
  pause
  exit /b
)
echo Python not found
pause
