@echo off
setlocal
cd /d "%~dp0"
where py.exe >nul 2>nul
if errorlevel 1 (
    python desktop_main.py
) else (
    py -3 desktop_main.py
)
if errorlevel 1 pause
