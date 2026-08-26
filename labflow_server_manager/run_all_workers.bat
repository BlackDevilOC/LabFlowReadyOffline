@echo off
title LabFlow Server Manager - Dual Workers
echo ========================================================
echo        LabFlow Server Manager Dual Worker Engine
echo ========================================================
echo.
echo Starting Worker 1 (Background Traffic Engine on Port 8000)...
start "Worker 1 Engine (8000)" cmd /c "%~dp0run_worker1_engine.bat"

echo Starting Worker 2 (Visual Admin Control Panel on Port 9000)...
start "Worker 2 Admin (9000)" cmd /c "%~dp0run_worker2_admin.bat"

echo.
echo Both workers launched!
echo Open your browser to: http://127.0.0.1:9000
echo.
pause
