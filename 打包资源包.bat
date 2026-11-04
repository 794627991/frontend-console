@echo off
chcp 936 >nul
rem ============================================================
rem 离线资源包打包（只打 .fcpk，不打包 exe）
rem
rem 四档预设 + 自定义：
rem   1 全量包        八项全含（约 1.6GB，含 OnlyOffice）
rem   2 基础资源包    WebView2 + .NET + Python 依赖（工具本体环境）
rem   3 claude 包     Claude CLI + Node + Git + bili 内置引擎
rem   4 额外拓展包    OnlyOffice（Word/Excel/PPT 全功能编辑，约 916MB）
rem   自定义          输入 kinds 逗号分隔（高级）
rem
rem 产物：dist/releases/前端控制台-资源包.fcpk
rem        子集包带后缀，如 前端控制台-资源包-claude.fcpk
rem
rem 命令行带参数：
rem   打包资源包.bat --preset base
rem   打包资源包.bat --kinds claude,node --out D:/交付
rem ============================================================
cd /d "%~dp0"
if not exist "dist" mkdir "dist"

set "PY="
set "PYFALLBACK=%LOCALAPPDATA%/Programs/Python/Python314/python.exe"
where python.exe >nul 2>&1
if not errorlevel 1 for /f "delims=%%i" in ('where python.exe') do if not defined PY set "PY=%%i"
if not defined PY set "PY=%PYFALLBACK%"
if not exist "%PY%" (
  echo [失败] 找不到 python.exe，请安装 Python 或加入 PATH
  pause
  exit /b 1
)

set "ARGS=%*"
if "%ARGS%"=="" (
  echo.
  echo   回车 = 全量包（八项全含，约 1.6GB）
  echo   或选择档位 / 输入自定义项：
  echo     1  全量包        八项全含（含 OnlyOffice）
  echo     2  基础资源包    WebView2 + .NET + Python 依赖
  echo     3  claude 包     Claude CLI + Node + Git + bili
  echo     4  额外拓展包    OnlyOffice 全功能 Office 编辑
  echo   自定义例：claude          只打 Claude CLI
  echo           claude,node      打两项
  echo           onlyoffice       只打 OnlyOffice
  echo.
  set /p KINDINPUT=  请输入（回车=全量）:
)
rem 全审 N1：cmd 对括号块做解析期一次性展开，块内 %KINDINPUT% 在进块前就已换成
rem 旧值（空）。档位映射必须在块外做。
if defined KINDINPUT (
  if "%KINDINPUT%"=="1" set "ARGS=--preset full"
  if "%KINDINPUT%"=="2" set "ARGS=--preset base"
  if "%KINDINPUT%"=="3" set "ARGS=--preset claude"
  if "%KINDINPUT%"=="4" set "ARGS=--preset ext"
)
rem 1-4 未命中（自定义 kinds）——ARGS 仍空时补
if not defined ARGS if defined KINDINPUT set "ARGS=--kinds %KINDINPUT%"

echo ==============================================
echo   离线资源包打包
echo ==============================================
set PYTHONIOENCODING=gbk
"%PY%" src/build.py --offline %ARGS%
if errorlevel 1 goto fail

:ok
echo.
echo ==============================================
echo [成功] 产物在 dist/releases/ 下
echo   把这个 .fcpk 发给需要的同事，
echo   工具内「设置 - 外部依赖安装」选它即可。
echo ==============================================
pause
exit /b 0

:fail
echo.
echo ==============================================
echo [失败] 资源包未产出，看上面的报错
echo   常见原因：dist/offline_pkg 缺安装器，
echo             或 runtime/WebView2Fixed 不在
echo ==============================================
pause
exit /b 1
