@echo off
title LabFlow - Supabase Continuous Replica Worker
color 0b

echo =======================================================
echo     LABFLOW CONTINUOUS SUPABASE REPLICA WORKER         
echo =======================================================
echo.
echo Starting replication engine...
echo Checking for Python environment...

if exist ".venv\Scripts\python.exe" (
    echo Using project virtual environment (.venv)
    ".venv\Scripts\python.exe" replica_worker.py %*
) else (
    echo Using system Python
    python replica_worker.py %*
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Replica worker exited with code %ERRORLEVEL%
    pause
)
