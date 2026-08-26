@echo off
title LabFlow Git Repository Separator
echo ========================================================
echo       LabFlow - Create & Separate Offline Git Repository
echo ========================================================
echo.
echo WARNING: This script will disconnect your current workspace from the
echo old online git repository and create a brand-new offline git repository.
echo.
set /p CONFIRM="Are you sure you want to initialize a NEW git repository? (Y/N): "
if /i "%CONFIRM%" neq "Y" (
    echo Operation cancelled.
    pause
    exit /b
)

cd /d "%~dp0"
echo.
echo [1/4] Removing old git origin link...
git remote remove origin 2>nul

echo [2/4] Initializing fresh git repository...
git init
git branch -M main

echo [3/4] Adding all local offline files...
git add .

echo [4/4] Creating initial offline commit...
git commit -m "Initial commit: LabFlow Standalone Offline Local Engine"

echo.
echo ========================================================
echo SUCCESS! Your offline codebase is now a separate Git repo.
echo ========================================================
echo To connect to your new GitHub/GitLab repository, run:
echo   git remote add origin https://github.com/YOUR_USERNAME/YOUR_OFFLINE_REPO.git
echo   git push -u origin main
echo.
pause
