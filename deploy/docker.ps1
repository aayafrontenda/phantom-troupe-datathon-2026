# CashGuard in Docker on Windows (Docker Desktop, WSL2 backend).
#   powershell -ExecutionPolicy Bypass -File deploy\docker.ps1            # GPU: real model + Ollama
#   powershell -ExecutionPolicy Bypass -File deploy\docker.ps1 -Tunnel    # + Cloudflare tunnel (named if CLOUDFLARE_TUNNEL_TOKEN is in .env, else trycloudflare.com)
#   powershell -ExecutionPolicy Bypass -File deploy\docker.ps1 -Cpu       # no GPU: demo analyzer
#   powershell -ExecutionPolicy Bypass -File deploy\docker.ps1 -Logs      # follow logs
#   powershell -ExecutionPolicy Bypass -File deploy\docker.ps1 -Down      # stop everything (data is kept)
param([switch]$Cpu, [switch]$Tunnel, [switch]$Named, [switch]$Logs, [switch]$Down, [switch]$NoBuild)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

docker info *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "Docker is not running. Start Docker Desktop and try again." -ForegroundColor Red; exit 1 }
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example" }

$files = @("-f", "docker-compose.yml")
if (-not $Cpu) { $files += @("-f", "docker-compose.gpu.yml") }
$profiles = @()
$token = Select-String -Path .env -Pattern '^CLOUDFLARE_TUNNEL_TOKEN=\S+' -Quiet
if ($Tunnel -and $token) { $Named = $true; $Tunnel = $false }
if ($Tunnel) { $profiles += @("--profile", "tunnel") }
if ($Named) { $profiles += @("--profile", "tunnel-named") }

if ($Down) { docker compose @files --profile tunnel --profile tunnel-named down; exit $LASTEXITCODE }
if ($Logs) { docker compose @files @profiles logs -f --tail 200; exit 0 }

$port = 8000
$line = Select-String -Path .env -Pattern '^PORT=(\d+)' | Select-Object -First 1
if ($line) { $port = [int]$line.Matches[0].Groups[1].Value }

$up = @("up", "-d")
if (-not $NoBuild) { $up += "--build" }
Write-Host "Starting CashGuard ($(if ($Cpu) {'demo analyzer, CPU'} else {'real model, GPU'}))... first build takes 10-20 minutes." -ForegroundColor Cyan
docker compose @files @profiles @up
if ($LASTEXITCODE -ne 0) {
  if (-not $Cpu) { Write-Host "If the error mentions 'nvidia' or 'GPU': update the NVIDIA driver, enable WSL2 in Docker Desktop, or run with -Cpu." -ForegroundColor Yellow }
  exit $LASTEXITCODE
}

Write-Host "Waiting for the service (the first start also downloads the VLM, ~6 GB)..."
$ready = $false
for ($i = 0; $i -lt 360; $i++) {
  try { if ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$port/ready").StatusCode -eq 200) { $ready = $true; break } } catch { }
  Start-Sleep -Seconds 5
}
if (-not $ready) { Write-Host "Not ready yet. Check: powershell -File deploy\docker.ps1 -Logs" -ForegroundColor Yellow; exit 1 }

$key = "$(docker compose @files exec -T app python -c 'from backend.app.config import get_settings; print(get_settings().resolve_api_key())')".Trim()
Write-Host ""
Write-Host "CashGuard is up:  http://127.0.0.1:$port" -ForegroundColor Green
Write-Host "Jury API key:     $key"
if ($Named) { Write-Host "Named tunnel is running: open the public hostname set for it in Cloudflare (service http://app:8000)." -ForegroundColor Green }
if ($Tunnel) {
  $url = $null
  for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    $m = (docker compose @files @profiles logs cloudflared 2>&1 | Select-String -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1)
    if ($m) { $url = $m.Matches[0].Value } else { Start-Sleep -Seconds 2 }
  }
  if ($url) { Write-Host "Public address:   $url" -ForegroundColor Green } else { Write-Host "Tunnel address not found yet: docker compose logs cloudflared" -ForegroundColor Yellow }
}
