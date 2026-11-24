@echo off
chcp 936 >nul
rem ===== debug 打包（2026-11-24 用户令）=====
rem 与 打包.bat 同一管线、同一 electron-builder NSIS 流程，唯一区别：
rem   HG_NO_ENCRYPT=1 -- 后端不做 Cython pyd，_internal\src\ 明文源码随包，
rem   装完能在安装目录里直接看/改源码。
rem 产物：dist\electron_setup_debug\前端控制台调试版-Setup-<版本>.exe
rem data 保全：与 release 完全一致（installer.nsh 保留 resources\backend\data）
rem 故不检查 MSVC（pyd 编译才需要），也不需要 zip/electron-shell 目录。
cd /d "%~dp0"

rem ---- 找 Python（PATH 优先，回退本机 Python314 用户安装路径）----
set "PY="
set "PYFALLBACK=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
where python.exe >nul 2>nul
if not errorlevel 1 for /f "delims=" %%i in ('where python.exe') do if not defined PY set "PY=%%i"
if not defined PY set "PY=%PYFALLBACK%"
if not exist "%PY%" (
  echo [失败] 找不到 python.exe，请安装 Python 或配好 PATH
  pause
  exit /b 1
)

rem ---- line-ending guard (2026-11-23: LF pollution makes cmd split
rem CJK lines into junk commands. Keep this block pure ASCII and
rem blockless: no if-parens, no goto -- python does detect+msg+pause+exit)
"%PY%" -c "import sys,os;b=open(sys.argv[1],'rb').read();bad=b.count(b'\n')!=b.count(b'\r\n');print('[FAIL] This script has LF-only line endings. Convert to CRLF, then rerun.') if bad else None;os.system('pause') if bad else None;sys.exit(1 if bad else 0)" "%~f0"
if errorlevel 1 exit /b 1

echo ==============================================
echo   前端控制台 调试安装包（源码明文）
echo ==============================================
set PYTHONIOENCODING=gbk
set HG_NO_ENCRYPT=1

rem ---- 第 1 步：PyInstaller 出后端（含源码明文），约 3~6 分钟 ----
echo ===== [1/2] 打包后端（源码明文）=====
"%PY%" src\build.py
if errorlevel 1 (
  echo.
  echo [失败] 后端打包未通过（上方有具体原因），未生成安装包
  pause
  exit /b 1
)
if not exist "dist\前端控制台_debug\前端控制台\前端控制台.exe" (
  echo [失败] 未找到后端 exe，安装包不出
  pause
  exit /b 1
)
rem ---- 自检（同正包：启动 + 全部模块 import）----
"dist\前端控制台_debug\前端控制台\前端控制台.exe" --selftest
if errorlevel 1 (
  echo [失败] selftest 非零退出
  pause
  exit /b 1
)
"%PY%" -c "import io,sys; sys.stdout.reconfigure(errors='replace'); print(io.open(r'dist\前端控制台_debug\前端控制台\selftest_result.txt', encoding='utf-8', errors='replace').read(), end='')"
findstr /C:"selftest FAIL" "dist\前端控制台_debug\前端控制台\selftest_result.txt" >nul
if not errorlevel 1 (
  echo [失败] selftest 报 FAIL，安装包不出
  pause
  exit /b 1
)

rem ---- 第 2 步：electron-builder 出 Setup.exe ----
where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo [失败] 找不到 npm，请先安装 Node.js 22.12+
  pause
  exit /b 1
)
rem Electron 45 的 engines 硬要求 node >=22.12.0
node -e "const v=process.versions.node.split('.').map(Number);process.exit(v[0]>22||(v[0]===22&&v[1]>=12)?0:1)"
if errorlevel 1 (
  echo [失败] Electron 45 需要 Node.js 22.12+，当前版本不够
  node -v
  pause
  exit /b 1
)
if not exist "electron\node_modules\electron\dist\electron.exe" (
  echo [首次] 安装 Electron 依赖（约 100MB），请稍候...
  pushd electron
  call npm install
  if not exist "node_modules\electron\dist\electron.exe" (
    set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
    node node_modules\electron\install.js
  )
  popd
)
echo ===== [2/2] electron-builder NSIS（约 2~3 分钟）=====
pushd electron
set "ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/"
call npx electron-builder --win nsis --config electron-builder.debug.json
popd
if errorlevel 1 (
  echo.
  echo [失败] 安装包生成未通过（上方有具体原因）
  pause
  exit /b 1
)

rem ---- asar 守卫：preload/guest-preload/passwords/pw-ipc 漏一个=装完即瘫 ----
pushd electron
call npx asar list ..\dist\electron_setup_debug\win-unpacked\resources\app.asar > "%TEMP%\fc_asar_dbg.txt"
findstr /C:"\preload.js" "%TEMP%\fc_asar_dbg.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 preload.js
  pause
  exit /b 1
)
findstr /C:"\guest-preload.js" "%TEMP%\fc_asar_dbg.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 guest-preload.js（自定义脚本会静默失效）
  pause
  exit /b 1
)
findstr /C:"\passwords.js" "%TEMP%\fc_asar_dbg.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 passwords.js（密码存储无法工作）
  pause
  exit /b 1
)
findstr /C:"\pw-ipc.js" "%TEMP%\fc_asar_dbg.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 pw-ipc.js（密码 IPC 无法注册）
  pause
  exit /b 1
)
del "%TEMP%\fc_asar_dbg.txt" >nul 2>nul
popd

rem ---- 源码明文守卫：debug 的立身之本，缺了就不是 debug 包 ----
if not exist "dist\前端控制台_debug\前端控制台\_internal\src\main.py" (
  echo [失败] 后端 _internal\src\main.py 不在场，源码明文丢失，禁止出包
  pause
  exit /b 1
)

echo.
echo ===== 完成 =====
for %%f in ("dist\electron_setup_debug\前端控制台调试版-Setup-*.exe") do echo 安装包：%%~ff
echo 安装后源码在：^<安装目录^>\resources\backend\_internal\src\
echo 数据保障：升级/卸载保留 ^<安装目录^>\resources\backend\data（与正式版同一套）
echo 记录已记：dist\打包记录.txt
>>"dist\打包记录.txt" echo [%date% %time%] 调试安装包 成功
pause
exit /b 0
