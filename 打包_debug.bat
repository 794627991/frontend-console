@echo off
chcp 936 >nul
rem 调试打包（v3.5.247）：与 打包.bat 同管线，唯一区别=跳过资源加密，
rem web/前端源码保持明文（可直接查看/改 dist 内文件）；且不进发布流
rem （不打 zip、不进 releases）——该包仅供调试，勿分发给同事。
rem 双击可用：成功/失败窗口停留，结果记 dist\打包记录.txt
cd /d "%~dp0"
if not exist "dist" mkdir "dist"
rem 找 Python（同 打包.bat：PATH 优先，回退本机 Python314 用户安装路径）
set "PY="
set "PYFALLBACK=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
where python.exe >nul 2>&1
if not errorlevel 1 for /f "delims=" %%i in ('where python.exe') do if not defined PY set "PY=%%i"
if not defined PY set "PY=%PYFALLBACK%"
if not exist "%PY%" (
  echo [失败] 找不到 python.exe，请安装 Python 或配好 PATH
  pause
  exit /b 1
)
echo ==============================================
echo   前端控制台 调试打包（源码明文，不发布）
echo ==============================================
set PYTHONIOENCODING=gbk
set HG_NO_ENCRYPT=1
"%PY%" src\build.py
if errorlevel 1 goto fail
if not exist "dist\前端控制台_debug\前端控制台\前端控制台.exe" goto fail

rem 自检（同正包：启动+全部模块 import）
"dist\前端控制台_debug\前端控制台\前端控制台.exe" --selftest
rem v3.5.268(复核):selftest崩溃态(TypError等)exit非零——findstr查不到FAIL行会假报成功,补errorlevel兜底
if errorlevel 1 goto fail
"%PY%" -c "import io,sys; sys.stdout.reconfigure(errors='replace'); print(io.open(r'dist\前端控制台_debug\前端控制台\selftest_result.txt', encoding='utf-8', errors='replace').read(), end='')"
findstr /C:"selftest FAIL" "dist\前端控制台_debug\前端控制台\selftest_result.txt" >nul && goto fail

:ok
echo.
echo ==============================================
echo [成功] 调试包: dist\前端控制台_debug + 同名zip在dist根（勿分发）
echo  记录已记: dist\打包记录.txt
echo ==============================================
>>"dist\打包记录.txt" echo [%date% %time%] 调试包 成功
pause
exit /b 0

:fail
echo.
echo ==============================================
echo [失败] 打包未成功，把上方报错发截图/全文
echo  记录已记: dist\打包记录.txt
echo ==============================================
>>"dist\打包记录.txt" echo [%date% %time%] 调试包 失败
pause
exit /b 1
