@echo off
rem 跟随 bat 所在目录（源码 zip 解压到任何机器/任何路径都能直接双击）
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw.exe src\main.py
) else (
  rem 无 pythonw（极简安装）退化为带控制台的 python，报错至少可见
  start "" python.exe src\main.py
)
