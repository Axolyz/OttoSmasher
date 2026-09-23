@echo off
setlocal
cd /d "%~dp0"
set "PATH=%CD%\.runtime\envs\core;%CD%\.runtime\envs\core\Library\bin;%CD%\.runtime\envs\core\Scripts;%PATH%"
if not exist ".runtime\envs\core\python.exe" (
 echo Run powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1 first.
 pause
 exit /b 1
)
".runtime\envs\core\python.exe" -m ottosmasher.cli ui library
