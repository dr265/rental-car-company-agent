# Car Rental WhatsApp AI Agent - Launcher (PowerShell)
# Run this in PowerShell: .\launch.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Push-Location $ScriptDir

Write-Host ""
Write-Host "============================================"
Write-Host "  Car Rental WhatsApp AI Agent - Launcher"
Write-Host "============================================"
Write-Host ""

# 1. Config file
if (-not (Test-Path "backend\.env")) {
    Write-Host "[ERROR] backend\.env not found." -ForegroundColor Red
    Write-Host "        Copy backend\.env.example to backend\.env and fill in your KAPSO and LLM keys."
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# 2. Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] Python not found on PATH. Install Python 3.11+ first." -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# 3. npm optional
$HaveNpm = $true
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    $HaveNpm = $false
    Write-Host "[WARN] npm not found - skipping Next.js dev server." -ForegroundColor Yellow
    Write-Host "        Backend console still at http://localhost:8022/"
}

# 4. Backend venv + deps
$Py = Join-Path $ScriptDir "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "[setup] Creating virtual environment (one time)..."
    Push-Location "backend"
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] venv creation failed." -ForegroundColor Red
        Pop-Location
        Read-Host "Press Enter to exit"
        exit 1
    }
    Pop-Location
}
if (-not (Test-Path $Py)) {
    Write-Host "[ERROR] $Py was not created. Delete backend\.venv and run again." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[setup] Installing backend dependencies..."
& $Py -m pip install --disable-pip-version-check -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Backend dependency installation failed." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# 5. Frontend deps
if ($HaveNpm) {
    if (-not (Test-Path "frontend\node_modules")) {
        Write-Host "[setup] Installing frontend dependencies (one time)..."
        Push-Location "frontend"
        npm install
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Frontend dependency installation failed." -ForegroundColor Red
            Pop-Location
            Read-Host "Press Enter to exit"
            exit 1
        }
        Pop-Location
    }
}

# 6. Launch
Write-Host "[start] Backend  -> http://localhost:8022   (API docs at /docs)"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$ScriptDir\backend'; & '$Py' main.py" -WindowTitle "Car Rental Backend (8022)"

if ($HaveNpm) {
    Write-Host "[start] Console  -> http://localhost:3020   (live reload)"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$ScriptDir\frontend'; npm run dev" -WindowTitle "Car Rental Console (3020)"
}

Write-Host ""
Write-Host "Services launching in separate windows."
Write-Host "  * Website / console : http://localhost:3020   (Next.js dev)"
Write-Host "  * Backend + API     : http://localhost:8022   (/ui serves the console too)"
Write-Host "  * API docs          : http://localhost:8022/docs"
Write-Host "  Keep those windows open; close them to stop the agent."
Write-Host ""

Start-Sleep -Seconds 8
if ($HaveNpm) {
    Start-Process "http://localhost:3020"
} else {
    Start-Process "http://localhost:8022/"
}

Pop-Location
