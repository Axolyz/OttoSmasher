@echo off
rem otto (stage A): call the running OttoSmasher with the project .venv
set PYTHONUTF8=1
"%~dp0..\.venv\Scripts\python.exe" -m ottosmasher.cli %*
