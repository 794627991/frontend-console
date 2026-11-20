@echo off
chcp 936 >nul
rem 一键出壳安装包（Electron 迁移 P1/P2）：后端正包（PyInstaller+Cython pyd）
rem + electron-builder NSIS → dist\electron_setup\前端控制台-Setup-*.exe
rem 依赖（本机已就绪）：Python314 + pip cython + VS BuildTools（D 盘）+ Node/npm
rem + electron\node_modules（首次跑 electron 下 npm install）。
rem 改代码后想出包就跑本脚本；中途失败窗口停留显示原因。
cd /d "%~dp0"

rem ---- Python 解析（PATH 优先，退回本机 Python314）----
set "PY="
set "PYFALLBACK=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
where python.exe >nul 2>nul
if not errorlevel 1 for /f "delims=" %%i in ('where python.exe') do if not defined PY set "PY=%%i"
if not defined PY set "PY=%PYFALLBACK%"
if not exist "%PY%" (
  echo [失败] 找不到 python.exe：请安装 Python 或加入 PATH
  pause
  exit /b 1
)

rem ---- MSVC 工具链（本机 BuildTools 装在 D 盘，pyd 编译必需）----
set "FC_MSVC_BT=D:\AI_PROJECT\msvc-buildtools"
if not exist "%FC_MSVC_BT%\VC\Tools\MSVC" (
  echo [失败] 未找到 MSVC：%FC_MSVC_BT% —— BuildTools 被移动/删除？改本脚本的 FC_MSVC_BT
  pause
  exit /b 1
)

rem ---- 第 1 步：后端正包 ----
echo ===== [1/2] 后端正包（PyInstaller + Cython pyd，约 4~6 分钟）=====
"%PY%" src\build.py
if errorlevel 1 (
  echo.
  echo [失败] 后端打包未通过（上方有具体原因），未继续出安装包。
  pause
  exit /b 1
)

rem ---- 第 2 步：electron-builder 出 Setup.exe ----
where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo [失败] 找不到 npm：请先安装 Node.js 22.12+
  pause
  exit /b 1
)
rem Electron 45.4.1 的 engines 硬要求 node >=22.12.0
node -e "const v=process.versions.node.split('.').map(Number);process.exit(v[0]>22||(v[0]===22&&v[1]>=12)?0:1)"
if errorlevel 1 (
  echo [失败] Electron 45 需要 Node.js 22.12+，当前版本：
  node -v
  pause
  exit /b 1
)
if not exist "electron\node_modules\electron\dist\electron.exe" (
  rem electron 44/45 无 postinstall（无 scripts 字段，bin.install-electron
  rem =install.js）——npm install 不会自动下载 dist，须手动跑安装脚本
  echo [首次] 安装 Electron 构建依赖（约 100MB，配国内镜像）...
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
call npx electron-builder --win nsis
popd
if errorlevel 1 (
  echo.
  echo [失败] 安装包构建未通过（上方有具体原因）。
  pause
  exit /b 1
)

rem ---- P0 审计守卫：preload/guest-preload/passwords 必须进 asar（漏一次=装机残）----
pushd electron
call npx asar list ..\dist\electron_setup\win-unpacked\resources\app.asar > "%TEMP%\fc_asar.txt"
findstr /C:"preload.js" "%TEMP%\fc_asar.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 preload.js——package.json files 清单漏了，禁止发布
  pause
  exit /b 1
)
findstr /C:"guest-preload.js" "%TEMP%\fc_asar.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 guest-preload.js——自动填充/保存会静默失效
  pause
  exit /b 1
)
findstr /C:"passwords.js" "%TEMP%\fc_asar.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 passwords.js——密码存储无法启动
  pause
  exit /b 1
)
findstr /C:"pw-ipc.js" "%TEMP%\fc_asar.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 pw-ipc.js——密码 IPC 无法注册
  pause
  exit /b 1
)
del "%TEMP%\fc_asar.txt" >nul 2>nul
popd

echo.
echo ===== 完成 =====
for %%f in ("dist\electron_setup\前端控制台-Setup-*.exe") do echo 安装包：%%~ff
echo 装机升级：直接重跑 Setup.exe（oneClick=false 会走向导，装到原目录即覆盖升级）
pause
