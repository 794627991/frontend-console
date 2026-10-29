@echo off
chcp 936 >nul
rem ============================================================
rem  离线资源包打包（只打 .fcpk，不打包 exe）
rem
rem  给已经发出去的工具补环境用：WebView2 / .NET / Node / Git /
rem  Claude CLI / Python 依赖，六项全量约 706MB。
rem
rem  用法（三种）：
rem    1. 双击本 bat            -> 全量打包
rem    2. 双击后按提示输入       -> 只打某几项
rem    3. 命令行带参数：
rem        打包资源包.bat --kinds claude
rem        打包资源包.bat --kinds claude,node --out D:\交付
rem
rem  产物：dist\releases\前端控制台-资源包.fcpk
rem        （子集包带后缀，如 前端控制台-资源包-claude.fcpk）
rem ============================================================
cd /d "%~dp0"
if not exist "dist" mkdir "dist"

set "PY="
set "PYFALLBACK=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
where python.exe >nul 2>&1
if not errorlevel 1 for /f "delims=" %%i in ('where python.exe') do if not defined PY set "PY=%%i"
if not defined PY set "PY=%PYFALLBACK%"
if not exist "%PY%" (
  echo [失败] 找不到 python.exe，请安装 Python 或加入 PATH
  pause
  exit /b 1
)

set "ARGS=%*"
if "%ARGS%"=="" (
  echo.
  echo   直接回车 = 全量打包（六项，约 706MB）
  echo   或输入要打的项，逗号分隔：
  echo     webview2,dotnet,node,git,claude,pydeps
  echo   例：claude       （只打 Claude CLI，约 270MB）
  echo       claude,node  （打两项）
  echo.
  set /p KINDINPUT=  请输入（回车=全量）:
)
rem 全审 N1：cmd 对括号块做解析期一次性展开，块内 %KINDINPUT% 在进块前就已换成旧值
rem （空）——无论输入什么都会变成 "--kinds "。必须把这一行移到块外。
if defined KINDINPUT set "ARGS=--kinds %KINDINPUT%"

echo ==============================================
echo   离线资源包打包
echo ==============================================
set PYTHONIOENCODING=gbk
"%PY%" src\build.py --offline %ARGS%
if errorlevel 1 goto fail

:ok
echo.
echo ==============================================
echo [成功] 产物在 dist\releases\ 下
echo   把这个 .fcpk 发给需要的同事，
echo   工具内「设置 - 外部依赖安装」选它即可。
echo ==============================================
pause
exit /b 0

:fail
echo.
echo ==============================================
echo [失败] 资源包未产出，看上面的报错
echo   常见原因：dist\offline_pkg 缺安装器，
echo             或 runtime\WebView2Fixed 不在
echo ==============================================
pause
exit /b 1
