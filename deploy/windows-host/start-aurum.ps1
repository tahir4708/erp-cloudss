# Build and start AURUM signal desk in Docker (port 8050).
# Run from repo root after Docker Desktop is up.

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Repo

Write-Host "Pulling latest code..."
git pull origin main 2>$null

Write-Host "Building and starting aurum-signals on port 8050..."
docker compose down 2>$null
docker compose up -d --build

Write-Host ""
Write-Host "AURUM UI: http://182.180.149.2:8050"
Write-Host "Health:   http://182.180.149.2:8050/api/health"
docker compose ps
