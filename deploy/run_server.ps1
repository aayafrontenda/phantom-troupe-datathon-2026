# Запуск сервиса на ROG (Windows) с автоперезапуском при падении.
# Из корня репозитория:   powershell -ExecutionPolicy Bypass -File deploy\run_server.ps1
# Настройки — в файле .env (скопируйте .env.example). ANALYZER по умолчанию здесь = ml.

$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (Test-Path ".venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }
if (-not $env:ANALYZER) { $env:ANALYZER = "ml" }
$env:PYTHONUTF8 = "1"
New-Item -ItemType Directory -Force -Path storage | Out-Null

# web UI: built from frontend/ when missing (needs Node 20+)
if (-not (Test-Path "frontend\dist\index.html")) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "== сборка интерфейса (frontend/)"
        Push-Location frontend
        if (-not (Test-Path "node_modules")) { npm ci --silent }
        npm run build --silent
        Pop-Location
    } else {
        Write-Host "!! Node/npm не найден, а frontend\dist отсутствует: установите Node 20+ и выполните npm ci; npm run build в frontend\" -ForegroundColor Yellow
    }
}

while ($true) {
    Write-Host "== $(Get-Date -Format 'HH:mm:ss') запуск сервиса (ANALYZER=$env:ANALYZER) на http://127.0.0.1:8000"
    python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000   # лог: storage\server.log
    Write-Host "Сервис остановился, перезапуск через 3 с... (Ctrl+C дважды, чтобы выйти)"
    Start-Sleep -Seconds 3
}
