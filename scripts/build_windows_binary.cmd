@echo off
setlocal

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0build_windows_binary.ps1" %*
exit /b %ERRORLEVEL%
