@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\one_click_deploy.ps1" %*
exit /b %ERRORLEVEL%
