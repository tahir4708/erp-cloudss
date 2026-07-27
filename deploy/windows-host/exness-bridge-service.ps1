# Run Exness MT5 price bridge on the Windows host (not inside Docker).
# Requires: MetaTrader 5 logged into Exness, Python with MetaTrader5 package.
# Usage: powershell -ExecutionPolicy Bypass -File exness-bridge-service.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path -Parent $Root
Set-Location $Repo

$py = "python"
if (-not (Get-Command $py -ErrorAction SilentlyContinue)) {
    $py = "py -3"
}

Write-Host "Installing bridge dependencies..."
& $py -m pip install --upgrade MetaTrader5 fastapi uvicorn httpx -q

$env:EXNESS_BRIDGE_PORT = "8787"
Write-Host "Starting Exness bridge on http://0.0.0.0:8787"
& $py exness_bridge.py
