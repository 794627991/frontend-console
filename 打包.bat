@echo off
chcp 936 >nul
rem 一键打包：dist\前端控制台\（onedir：exe+全部资源）
rem 双击即用；成功/失败窗口都停留显示结果，并落盘 dist\打包结果.txt
rem v3.4.96：修复 be5c669 起尾部丢失（:fail 标签不存在→goto 报错秒关窗，
rem 成功路径也无 pause——用户实锤「莫名其妙消失，看不到成败」）
cd /d "%~dp0"
if not exist "dist" mkdir "dist"
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

rem v2.3.8 自检（解密+全依赖 import，不碰单实例锁）
"dist\前端控制台\前端控制台.exe" --selftest
rem v3.4.96b: 自检结果为 UTF-8 文件, type 按码页直倒会花脸——
rem 经 python 按 UTF-8 读出显示（findstr 判定不受影响）
"%PY%" -c "import io,sys; sys.stdout.reconfigure(errors='replace'); print(io.open(r'dist\前端控制台\selftest_result.txt', encoding='utf-8', errors='replace').read(), end='')"
findstr /C:"selftest FAIL" "dist\前端控制台\selftest_result.txt" >nul && goto fail

:ok
echo.
echo ==============================================
echo [成功] 打包完成: dist\前端控制台echo 结果已记录: dist\打包结果.txt
echo ==============================================
>>"dist\打包结果.txt" echo [%date% %time%] 成功
pause
exit /b 0

:fail
echo.
echo ==============================================
echo [失败] 打包未成功——请把上方报错截图/复制
echo 结果已记录: dist\打包结果.txt
echo ==============================================
>>"dist\打包结果.txt" echo [%date% %time%] 失败
pause
exit /b 1
