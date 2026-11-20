@echo off
chcp 936 >nul
rem Electron 壳启动（换壳迁移 P1/P2/P3）：拉起后端 --headless + Electron 窗口。
rem 与 run.bat 配对：run.bat=旧 pywebview 形态，本脚本=Electron 壳形态。
rem 首次自动安装 Electron（约 100MB）；任何失败窗口停留显示原因。
rem 壳日志：%USERPROFILE%\.serialconsole_pro\electron-shell.log
cd /d "%~dp0electron"

where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [失败] 找不到 npm：请先安装 Node.js 22.12+（nodejs.org，勾选 Add to PATH）后重试
  pause
  exit /b 1
)

rem Electron 45.4.1 的 engines 硬要求 node >=22.12.0；低版本 npm install 会被拦
node -e "const v=process.versions.node.split('.').map(Number);process.exit(v[0]>22||(v[0]===22&&v[1]>=12)?0:1)"
if errorlevel 1 (
  echo [失败] Electron 45 需要 Node.js 22.12+，当前版本：
  node -v
  pause
  exit /b 1
)

rem 用 electron.exe 真身做安装信号（.bin 壳脚本在下载失败时也会存在）
if not exist "node_modules\electron\dist\electron.exe" (
  echo [首次运行] 安装 Electron（约 100MB，视网络 1~10 分钟）...
  call npm install
  if not exist "node_modules\electron\dist\electron.exe" (
    set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
    node node_modules\electron\install.js
  )
)

if not exist "node_modules\electron\dist\electron.exe" (
  echo [失败] Electron 安装不完整。国内网络重试方法：
  echo    1. set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
  echo    2. 删除 electron\node_modules 目录
  echo    3. 重新运行本脚本
  pause
  exit /b 1
)

rem 用户令：本脚本只做启动——start 直拉 electron.exe（GUI 子系统，无控制台
黑窗），cmd 窗口随即退出。cwd 已在 electron 目录（main.js 用 __dirname
定位，不依赖启动目录，但保险继承当前目录）
start "" "node_modules\electron\dist\electron.exe" .
exit /b 0
