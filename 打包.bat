@echo off
chcp 65001 >nul
rem 一键打包：dist\前端控制台.exe（spec 含 web/ico/vendor/blob/README 全部资源）
rem 双击即用；退出码非 0 或 exe 未生成时窗口停留供看报错
cd /d "%~dp0"
echo ==============================================
echo   前端控制台 一键打包
echo ==============================================
python.exe src\build.py
if errorlevel 1 goto fail
if not exist "dist\前端控制台.exe" goto fail
for %%A in ("dist\前端控制台.exe") do echo.
echo [OK] 打包完成: dist\前端控制台.exe (%%~zA 字节)
echo.
pause
exit /b 0
:fail
echo.
echo [失败] 打包未成功，请看上方报错
echo.
pause
exit /b 1
