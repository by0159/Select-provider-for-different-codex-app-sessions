@echo off
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Manage.ps1" -Action Install
set "result=%errorlevel%"
pause
exit /b %result%
