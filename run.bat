@echo off
chcp 936 >nul
rem 唯一启动入口（2026-11-23 用户令：run 只留一个）。Electron 壳 + 后端。
rem 运行时三优先级：
rem   1) electron\node_modules\electron\dist（npm 装出）
rem   2) ..\offline_runtime\electron（离线资源包装出——免 npm/网络）
rem   3) 都没有 → 本脚本自动安装（npm install，Electron ~100MB，镜像兜底）
rem 壳日志：工具内诊断面板 tag=shell（仅致命路径落 electron-shell.log）
cd /d "%~dp0electron"

rem ---- 优先级 2：离线运行时（资源包） ----
if not exist "node_modules\electron\dist\electron.exe" (
  if exist "..\offline_runtime\electron\electron.exe" (
    echo [离线] 使用资源包安装的 Electron 运行时
    start "" "..\offline_runtime\electron\electron.exe" .
    exit /b 0
  )
)

rem ---- 优先级 3：自动安装（需 Node.js 22.12+ / npm / 网络） ----
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [失败] 找不到 npm：请先安装 Node.js 22.12+（nodejs.org，勾选 Add to PATH）
  echo        或用离线资源包 / 调试包（打包_debug 产物自带 Electron 运行时）。
  pause
  exit /b 1
)
rem Electron 45.4.1 的 engines 硬要求 node ^>=22.12.0
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
  echo        或改用离线资源包 / 调试包（免网络）。
  pause
  exit /b 1
)

rem 本脚本只做启动：start 直拉 electron.exe（GUI 子系统，无控制台黑窗）
start "" "node_modules\electron\dist\electron.exe" .
exit /b 0
