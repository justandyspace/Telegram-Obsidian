Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$envFile = Join-Path $projectRoot ".env"
if (-not (Test-Path $envFile)) {
    throw ".env not found at $envFile"
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    python -m venv .venv
}

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
        return
    }
    $parts = $line -split "=", 2
    if ($parts.Count -ne 2) {
        return
    }
    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
}

if (-not $env:STATE_DIR -or $env:STATE_DIR.StartsWith("/")) {
    $env:STATE_DIR = (Join-Path $projectRoot ".data\state")
}
if (-not $env:CACHE_DIR -or $env:CACHE_DIR.StartsWith("/")) {
    $env:CACHE_DIR = (Join-Path $projectRoot ".data\cache")
}
if (-not $env:INDEX_DIR -or $env:INDEX_DIR.StartsWith("/")) {
    $env:INDEX_DIR = (Join-Path $projectRoot ".data\index")
}
if (-not $env:VAULT_PATH -or $env:VAULT_PATH.StartsWith("/data/vault")) {
    $env:VAULT_PATH = (Join-Path $projectRoot "local_obsidian_inbox")
}

New-Item -ItemType Directory -Force -Path $env:STATE_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:CACHE_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:INDEX_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $env:VAULT_PATH | Out-Null

$env:PYTHONPATH = "."

& $venvPython -m pip install -r requirements-dev.txt | Out-Host

$worker = Start-Process `
    -FilePath $venvPython `
    -ArgumentList "-m", "src.main", "--role", "worker" `
    -WorkingDirectory $projectRoot `
    -PassThru `
    -NoNewWindow

$bot = Start-Process `
    -FilePath $venvPython `
    -ArgumentList "-m", "src.main", "--role", "bot" `
    -WorkingDirectory $projectRoot `
    -PassThru `
    -NoNewWindow

Write-Host "Started worker PID=$($worker.Id), bot PID=$($bot.Id)"
Write-Host "VAULT_PATH=$($env:VAULT_PATH)"
Write-Host "Press Ctrl+C to stop both processes."

try {
    Wait-Process -Id $worker.Id, $bot.Id
}
finally {
    foreach ($pid in @($worker.Id, $bot.Id)) {
        try {
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
        catch {
        }
    }
}
