@echo off
rem otto (stage A): call the running OttoSmasher with the project .venv
"%~dp0..\.venv\Scripts\python.exe" -m ottosmasher.cli %*
