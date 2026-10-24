@echo off
setlocal EnableExtensions
title ZoomRideXX Car Rentals - WhatsApp AI Agent
cd /d "%~dp0"

echo.
echo  ==================================================
echo   ZoomRideXX Car Rentals - Website + WhatsApp AI Agent
echo  ==================================================
echo.

REM ---- 1. config file ----
if not exist "backend\.env" (
    echo [ERROR] backend\.env not found.
    echo         Copy backend\.env.example to backend\.env and fill in the
    echo         KAPSO and LLM keys, then run start.bat again.
    echo.
    pause
    exit /b 1
)

REM ---- 2. locate a Python interpreter for bootstrapping ----
set "BOOTPY="
where py >nul 2>nul
if not errorlevel 1 set "BOOTPY=py -3"
if not defined BOOTPY (
    where python >nul 2>nul
    if not errorlevel 1 set "BOOTPY=python"
)
if not defined BOOTPY (
    echo [ERROR] Python 3.11+ was not found on PATH.
    echo         Install Python from python.org and tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

REM ---- 3. backend virtual environment ----
set "PY=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [setup] Creating the backend virtual environment ^(one time^)...
    pushd "backend"
    %BOOTPY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create backend\.venv
        popd
        echo.
        pause
        exit /b 1
    )
    popd
)
if not exist "%PY%" (
    echo [ERROR] %PY% is missing. Delete backend\.venv and run start.bat again.
    echo.
    pause
    exit /b 1
)

REM ---- 4. backend dependencies ----
echo [check] Verifying backend dependencies...
"%PY%" -c "import fastapi,uvicorn,sqlalchemy,httpx,dotenv,pydantic,cryptography,jwt,multipart,pypdf,docx,openpyxl,xlrd,websockets,httptools,watchfiles" >nul 2>nul
if errorlevel 1 (
    echo [setup] Installing backend dependencies...
    "%PY%" -m pip install --disable-pip-version-check -r "backend\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Backend dependency installation failed - see the output above.
        echo.
        pause
        exit /b 1
    )
) else (
    echo [check] Backend dependencies already installed.
)

REM ---- 5. frontend (website + owner console, static export served by the backend) ----
REM "start.bat rebuild" forces a fresh Next.js export; otherwise the frontend
REM is rebuilt automatically whenever its sources are newer than the export,
REM so UI changes always show up after a restart.
set "REBUILD_CONSOLE="
if /i "%~1"=="rebuild" set "REBUILD_CONSOLE=1"
if not defined REBUILD_CONSOLE if not exist "frontend\out\index.html" set "REBUILD_CONSOLE=1"
if not defined REBUILD_CONSOLE (
    powershell -NoProfile -Command "$out=(Get-Item 'frontend\out\index.html').LastWriteTime; if (Get-ChildItem -Recurse -File 'frontend\src','frontend\public' -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt $out } | Select-Object -First 1) { exit 1 }"
    if errorlevel 1 set "REBUILD_CONSOLE=1"
)

if defined REBUILD_CONSOLE (
    where npm >nul 2>nul
    if errorlevel 1 (
        echo [WARN] npm was not found, so the Next.js console cannot be built.
        echo        The backend will serve the bundled console at http://localhost:8022/
    ) else (
        if not exist "frontend\node_modules" (
            echo [setup] Installing frontend dependencies ^(one time^)...
            pushd "frontend"
            call npm install
            if errorlevel 1 (
                echo [ERROR] npm install failed.
                popd
                echo.
                pause
                exit /b 1
            )
            popd
        )
        if exist "frontend\out" rmdir /s /q "frontend\out"
        echo [setup] Building the owner console ^(about a minute^)...
        pushd "frontend"
        call npm run build
        if errorlevel 1 (
            echo [ERROR] Frontend build failed - see the output above.
            popd
            echo.
            pause
            exit /b 1
        )
        popd
    )
)

REM ---- 6. free the app port ----
REM Close the previous backend window AND the python process it started.
REM (taskkill's WINDOWTITLE filter does not see console windows, so match the
REM command line instead.) Then fall back to killing whatever still listens.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*backend*python.exe*main.py*') -or ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*backend*main.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
set "KILLED_OLD="
for /f "tokens=5" %%p in ('netstat -a -n -o ^| findstr /r /c:":8022 .*LISTENING"') do (
    if not defined KILLED_OLD echo [setup] Port 8022 is busy ^(pid %%p^) - stopping the old backend...
    taskkill /F /T /PID %%p >nul 2>nul
    set "KILLED_OLD=1"
)
REM taskkill returns before Windows releases the socket; give it a moment so the
REM fresh instance can bind instead of exiting with "address already in use".
if defined KILLED_OLD ping -n 3 127.0.0.1 >nul 2>nul

REM ---- 7. launch backend + console ----
echo.
echo [start] Serving the website + WhatsApp agent at http://localhost:8022
start "ZoomRideXX Backend" /D "%~dp0backend" cmd /k ""%PY%" main.py"

echo [wait ] Waiting for the backend to become ready...
REM curl.exe ships with Windows 10/11. Poll 127.0.0.1 (not "localhost", which can
REM resolve to IPv6 while uvicorn binds IPv4) until /api/health answers.
curl.exe -s -f -o nul --noproxy "*" --max-time 3 --retry 60 --retry-delay 1 --retry-connrefused http://127.0.0.1:8022/api/health
if errorlevel 1 (
    echo [WARN] The backend did not answer on port 8022.
    echo        Check the "ZoomRideXX Backend" window for the error.
    echo.
    pause
    exit /b 1
)

echo.
echo  Ready.
echo   * Car rental website           : http://localhost:8022/
echo   * Owner console / admin        : http://localhost:8022/console
echo   * API docs                     : http://localhost:8022/docs
echo   * Health                       : http://localhost:8022/api/health
echo.
echo  Keep the "ZoomRideXX Backend" window open; close it to stop the agent.
echo.
start "" http://localhost:8022/
exit /b 0
