@echo off
chcp 65001 >nul
title Race-O-Rama Online - dev
cd /d "%~dp0"
rem Entwicklungsmodus: startet den Launcher direkt aus dem Quellcode
powershell -NoProfile -ExecutionPolicy Bypass -File get_melonds.ps1
if exist .venv call .venv\Scripts\activate.bat
python -c "import webview" 2>nul || python -m pip install pywebview
python -c "import sdl2, sdl2dll" 2>nul || python -m pip install pysdl2 pysdl2-dll
python main.py
pause
