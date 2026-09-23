@echo off
rem 跟随 bat 所在目录（源码 zip 解压到任何机器/任何路径都能直接双击）
cd /d "%~dp0"
rem 入口优先级：pythonw（窗口化）→ pyw（py launcher 窗口化，官网安装默认
rem 只有 py/pyw 在 PATH，python.exe 不在——实测机即此形态）→ python（带
rem 控制台，报错至少可见）
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw.exe src\main.py
  exit /b
)
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw.exe src\main.py
  exit /b
)
where python >nul 2>nul
if %errorlevel%==0 (
  start "" python.exe src\main.py
  exit /b
)
echo 未找到 Python：请安装 Python 3.12+（勾选 py launcher），或把 python.exe 加入 PATH。
pause
