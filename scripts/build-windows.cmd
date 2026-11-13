@echo off
REM Script auxiliar para generar o preparar el instalador de Windows.
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0build-windows.ps1"
exit /b %ERRORLEVEL%
