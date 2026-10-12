@echo off
chcp 936 >nul
rem һ�������dist\ǰ�˿���̨\��onedir��exe+ȫ����Դ��
rem ˫�����ã��ɹ�/ʧ�ܴ��ڶ�ͣ����ʾ����������� dist\������.txt
rem v3.4.96���޸� be5c669 ��β����ʧ��:fail ��ǩ�����ڡ�goto ������ش���
rem �ɹ�·��Ҳ�� pause�����û�ʵ����Ī��������ʧ���������ɰܡ���
cd /d "%~dp0"
if not exist "dist" mkdir "dist"
rem ���� Python���� PATH���˻ر��� Python314 �û���װ·��
set "PY="
set "PYFALLBACK=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
where python.exe >nul 2>&1
rem v3.5.115 fix: resolve the FULL path via where. The old code kept the
rem bare name on success and then `if not exist "python.exe"` tested a
rem CWD-relative file - always missing - so the script misjudged failure
rem once Python got added to PATH. Fallback stays for PATH-less machines.
if not errorlevel 1 for /f "delims=" %%i in ('where python.exe') do if not defined PY set "PY=%%i"
if not defined PY set "PY=%PYFALLBACK%"
if not exist "%PY%" (
  echo [ʧ��] �Ҳ��� python.exe���밲װ Python ����� PATH
  pause
  exit /b 1
)
echo ==============================================
echo   ǰ�˿���̨ һ�����
echo ==============================================
set PYTHONIOENCODING=gbk
"%PY%" src\build.py
if errorlevel 1 goto fail
if not exist "dist\ǰ�˿���̨\ǰ�˿���̨.exe" goto fail

rem v2.3.8 �Լ죨����+ȫ���� import��������ʵ������
"dist\ǰ�˿���̨\ǰ�˿���̨.exe" --selftest
rem v3.4.96b: �Լ���Ϊ UTF-8 �ļ�, type ����ҳֱ���Ứ������
rem �� python �� UTF-8 ������ʾ��findstr �ж�����Ӱ�죩
"%PY%" -c "import io,sys; sys.stdout.reconfigure(errors='replace'); print(io.open(r'dist\ǰ�˿���̨\selftest_result.txt', encoding='utf-8', errors='replace').read(), end='')"
findstr /C:"selftest FAIL" "dist\ǰ�˿���̨\selftest_result.txt" >nul && goto fail

:ok
echo.
echo ==============================================
echo [�ɹ�] ������: dist\ǰ�˿���̨echo ����Ѽ�¼: dist\������.txt
echo ==============================================
>>"dist\������.txt" echo [%date% %time%] �ɹ�
pause
exit /b 0

:fail
echo.
echo ==============================================
echo [ʧ��] ���δ�ɹ���������Ϸ�������ͼ/����
echo ����Ѽ�¼: dist\������.txt
echo ==============================================
>>"dist\������.txt" echo [%date% %time%] ʧ��
pause
exit /b 1
