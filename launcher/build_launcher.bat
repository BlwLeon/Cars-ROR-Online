@echo off
chcp 65001 >nul
title Race-O-Rama Online - build
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
if errorlevel 1 echo. & echo Build failed - see output above.
pause
