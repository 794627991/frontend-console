@echo off
chcp 936 >nul
rem 一键打包：dist\前端控制台.exe（spec 含 web/ico/vendor/blob/README 全部资源）
rem 双击即用；失败时窗口停留供看报错
cd /d "%~dp0"
rem 解析 Python：先 PATH，退回本机 Python314 用户安装路径
set "PY=python.exe"
where %PY% >nul 2>&1
if errorlevel 1 set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PY%" (
  echo [失败] 找不到 python.exe：请安装 Python 或加入 PATH
  pause
  exit /b 1
)
echo ==============================================
echo   前端控制台 一键打包
echo ==============================================
set PYTHONIOENCODING=gbk
"%PY%" src\build.py
if errorlevel 1 goto fail
if not exist "dist\前端控制台\前端控制台.exe" goto fail
echo.
echo [OK] 打包完成: dist\前端控制台.exe
echo.
pause
exit /b 0
:fail
echo.
echo [失败] 打包未成功，请看上方报错
echo.
pause
exit /b 1
