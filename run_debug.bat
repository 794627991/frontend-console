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
pushd "%~dp0"

set HARNESS_DEBUG_WEB=1
set "ERRFILE=%~dp0run_debug_last_error.txt"

rem --- silent-failure guard -------------------------------------------------
rem pythonw/pyw have no console: if src\main.py dies on startup the user sees
rem a black frame flash and then nothing (no window, no log). Pre-flight an
rem import in the SAME interpreter before the async launch; on failure write
rem a breadcrumb and show a native message box (mshta has no console window).
set "PYEXE="
where pythonw >nul 2>nul
if %errorlevel%==0 set "PYEXE=pythonw.exe"
if not defined PYEXE (
  where pyw >nul 2>nul
  if %errorlevel%==0 set "PYEXE=pyw.exe"
)

if defined PYEXE (
  "%PYEXE%" -c "import sys; sys.path.insert(0, r'%CD%'); import src.main" >nul 2>nul
  if errorlevel 1 (
    call :fail "src main.py failed to start (import error). See run_debug_last_error.txt, or run with a console: python src\main.py"
    popd
    exit /b 1
  )
  start "" "%PYEXE%" src\main.py %*
  popd
  exit /b
)

where python >nul 2>nul
if %errorlevel%==0 (
  echo [warn] pythonw/pyw not found, falling back to python.exe
  python src\main.py %*
  pause
  popd
  exit /b
)
call :fail "Python not found on PATH."
popd
exit /b 1

:fail
rem Write a breadcrumb (always works), then try a native message box.
echo [%date% %time%] %~1> "%ERRFILE%"
start "" mshta "javascript:alert('start failed - see run_debug_last_error.txt');close();" >nul 2>nul
exit /b 1
