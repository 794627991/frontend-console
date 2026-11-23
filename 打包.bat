@echo off
chcp 936 >nul
rem ===== release 打包（2026-11-23 用户令：打包只留两个）=====
rem 一键三产物：①后端正包（PyInstaller+Cython pyd，含 releases 升级 zip）
rem ②离线资源包 .fcpk（含 Electron 运行时——资源包只在打 release 时出）
rem ③electron-builder NSIS → dist\electron_setup\前端控制台-Setup-*.exe
rem debug 包用 打包_debug.bat（自带 Electron 运行时）。
rem 依赖（本机已就绪）：Python314 + pip cython + VS BuildTools（D 盘）
rem + Node/npm + electron\node_modules（首次跑 electron 下 npm install）。
rem 中途失败窗口停留显示原因。
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

rem ---- line-ending guard (2026-11-23: LF pollution makes cmd split
rem CJK lines into junk commands. Keep this block pure ASCII and
rem blockless: no if-parens, no goto -- python does detect+msg+pause+exit)
"%PY%" -c "import sys,os;b=open(sys.argv[1],'rb').read();bad=b.count(b'\n')!=b.count(b'\r\n');print('[FAIL] This script has LF-only line endings. Convert to CRLF, then rerun.') if bad else None;os.system('pause') if bad else None;sys.exit(1 if bad else 0)" "%~f0"
if errorlevel 1 exit /b 1
rem ---- MSVC 工具链（pyd 编译必需。2026-11-23 实锤：D 盘 BuildTools 已移除，
rem 本机为 C 盘标准安装）——复审修订后的顺序与口径：
rem   ① 用户预设 FC_MSVC_BT 优先（P2-5）② 缺失则 vswhere 兜底（挪窝场景，
rem   N4：兜底必须排在深检前，否则成死代码）③ 深检对齐 python 侧
rem   cythonize_build._msvc_env：cl.exe 真身 + Windows SDK（Include+Lib，N10）
rem 行内反斜杠为字面量——GBK bat 补丁绝不走 heredoc 转义层（N1-N3 实锤）。
if not defined FC_MSVC_BT set "FC_MSVC_BT=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools"
if not exist "%FC_MSVC_BT%\VC\Tools\MSVC" for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "FC_MSVC_BT=%%i"
if not exist "%FC_MSVC_BT%\VC\Tools\MSVC" (
  echo [失败] 未找到 MSVC BuildTools（含 VC.Tools 组件）——请安装 VS BuildTools
  echo        或设环境变量 FC_MSVC_BT 指向安装根（其下有 VC\Tools\MSVC）。
  pause
  exit /b 1
)
set "FC_CL="
for /d %%v in ("%FC_MSVC_BT%\VC\Tools\MSVC\*") do if not defined FC_CL if exist "%%v\bin\Hostx64\x64\cl.exe" set "FC_CL=1"
if not defined FC_CL (
  echo [失败] MSVC 工具链不完整：VC\Tools\MSVC 下无 Hostx64/x64/cl.exe
  pause
  exit /b 1
)
if not exist "%ProgramFiles(x86)%\Windows Kits\10\Include" (
  echo [失败] 未找到 Windows SDK Include（Windows Kits\10）——pyd 编译必需
  pause
  exit /b 1
)
if not exist "%ProgramFiles(x86)%\Windows Kits\10\Lib" (
  echo [失败] 未找到 Windows SDK Lib（Windows Kits\10）——pyd 链接必需
  pause
  exit /b 1
)

rem ---- 第 1 步：后端正包（含 releases zip + 离线资源包 .fcpk）----
echo ===== [1/2] 后端正包 + 升级 zip + 离线资源包（约 4~8 分钟）=====
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
rem findstr 用前导 \ 做行首锚定（防 guest-preload.js 误命中 preload.js 检查）
pushd electron
call npx asar list ..\dist\electron_setup\win-unpacked\resources\app.asar > "%TEMP%\fc_asar.txt"
findstr /C:"\preload.js" "%TEMP%\fc_asar.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 preload.js——package.json files 清单漏了，禁止发布
  pause
  exit /b 1
)
findstr /C:"\guest-preload.js" "%TEMP%\fc_asar.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 guest-preload.js——自动填充/保存会静默失效
  pause
  exit /b 1
)
findstr /C:"\passwords.js" "%TEMP%\fc_asar.txt" >nul
if errorlevel 1 (
  popd
  echo [失败] app.asar 里没有 passwords.js——密码存储无法启动
  pause
  exit /b 1
)
findstr /C:"\pw-ipc.js" "%TEMP%\fc_asar.txt" >nul
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
for %%f in ("dist\releases\前端控制台-资源包.fcpk") do echo 资源包：%%~ff（含 Electron，源码形态离线可用）
echo 装机升级：直接重跑 Setup.exe（oneClick=false 会走向导，装到原目录即覆盖升级）
pause
