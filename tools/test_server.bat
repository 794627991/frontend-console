@echo off
rem ============================================================
rem SANDBOXED test-server launcher (rule set after the
rem 2026-11-13 incident: NEVER run `python -m src.server`
rem directly for API/browser testing)
rem
rem Incident: a bare test instance shared the REAL home-anchored
rem config.json + DATA_DIR, so test POSTs to /api/theme polluted
rem the user's real config (web_session / tftp_pane_h ...).
rem
rem This launcher redirects USERPROFILE to a temp sandbox so the
rem home-anchored config/data/log dirs all land in the sandbox.
rem Port stays 8765 (127.0.0.1 bind shadows the real app only
rem for loopback clients while this runs). Ctrl-C when done.
rem ============================================================
setlocal
set "FC_TEST_SANDBOX=%TEMP%\fc_test_sandbox_%RANDOM%"
mkdir "%FC_TEST_SANDBOX%" 2>nul
set "USERPROFILE=%FC_TEST_SANDBOX%"
set "CLAUDE_INLINE=1"
set "FC_APP_BOOT="
echo [test-server] sandbox HOME = %FC_TEST_SANDBOX%
echo [test-server] real config/data untouched (all writes go to sandbox)
rem This script lives in tools/; repo root is one level up.
cd /d "%~dp0.."
python -m src.server
