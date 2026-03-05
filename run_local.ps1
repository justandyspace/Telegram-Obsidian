if (Test-Path ".env") {
    foreach($line in Get-Content .env) {
        if($line -match '^\s*([^#]\w+)\s*=\s*(.*)') {
            [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim(), "Process")
        }
    }
} else {
    Write-Host "Warning: .env file not found."
}

if (-not $env:VAULT_PATH) { $env:VAULT_PATH = (Resolve-Path ".\local_obsidian_inbox").Path }
if (-not $env:STATE_DIR) { $env:STATE_DIR = (Resolve-Path ".\.data\state").Path }
if (-not $env:CACHE_DIR) { $env:CACHE_DIR = (Resolve-Path ".\.data\cache").Path }
if (-not $env:INDEX_DIR) { $env:INDEX_DIR = (Resolve-Path ".\.data\index").Path }
$env:APP_ROLE = "standalone"

Write-Host "Starting bot and worker in standalone mode..."
python -m src.main --role standalone

