@echo off
setlocal
title Attach fleet photos to the agent

cd /d "%~dp0" || (echo [X] could not enter the project folder & pause & exit /b 1)

where python >nul 2>nul
if errorlevel 1 (
  echo [X] python was not found on PATH. Install Python 3.11+ and retry.
  pause
  exit /b 1
)

if not exist "backend\.venv\Scripts\activate.bat" (
  echo [!] backend\.venv was not found.
  echo     Run start.bat once ^(it creates the environment^), then run this again.
  pause
  exit /b 1
)

call "backend\.venv\Scripts\activate.bat" || (
  echo [X] could not activate backend\.venv
  pause
  exit /b 1
)

python attach_vehicle_images.py %*
echo.
pause
