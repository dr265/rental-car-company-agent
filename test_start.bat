@echo off
echo test1
setlocal
echo test2
cd /d "%~dp0"
echo test3
if not exist "backend\.env" (
    echo test4
)
echo test5
where python >nul 2>nul
echo test6
if errorlevel 1 (
    echo test7
)
echo test8
set "PY=%~dp0backend\.venv\Scripts\python.exe"
echo PY is: %PY%
echo done
