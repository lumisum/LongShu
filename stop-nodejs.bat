@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-nodejs.ps1" %*
set "LONGSHU_EXIT=%ERRORLEVEL%"
if not "%LONGSHU_EXIT%"=="0" pause
exit /b %LONGSHU_EXIT%
