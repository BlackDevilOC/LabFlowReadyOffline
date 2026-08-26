@echo off
title LabFlow Worker 2 - Visual Admin Panel
echo ========================================================
echo        LabFlow Worker 2: Visual Admin Panel (Port 9000)
echo ========================================================
echo.
cd /d "%~dp0\.."
python labflow_server_manager/worker2_admin_panel.py
pause
