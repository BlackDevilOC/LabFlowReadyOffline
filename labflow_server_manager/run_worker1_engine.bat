@echo off
title LabFlow Worker 1 - Background Engine
echo ========================================================
echo        LabFlow Worker 1: Background Engine (Port 8000)
echo ========================================================
echo.
cd /d "%~dp0\.."
python labflow_server_manager/worker1_bg_engine.py
pause
