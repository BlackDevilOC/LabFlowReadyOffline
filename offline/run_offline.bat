@echo off
title LabFlow Offline Server
echo Starting LabFlow Standalone Offline Mode...
echo ------------------------------------------
cd %~dp0
..\.venv\Scripts\uvicorn app:app --host 127.0.0.1 --port 8001 --reload
pause
