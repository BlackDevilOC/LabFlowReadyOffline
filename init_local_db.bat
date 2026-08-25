@echo off
title LabFlow Local PostgreSQL Initializer & Inspector
echo ========================================================
echo    LabFlow Local PostgreSQL Database Initializer
echo ========================================================
echo.
cd /d "%~dp0"
python check_local_db.py
echo.
pause
