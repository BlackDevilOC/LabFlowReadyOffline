@echo off
title LabFlow Standalone Local Server Engine
echo ========================================================
echo        LabFlow Standalone Local Server Engine
echo ========================================================
echo.
cd /d "%~dp0\.."
python server_engine/server_main.py
pause
