param(
    [string]$PythonExe = "C:\Users\Desktop\AppData\Local\Programs\Python\Python312\python.exe",
    [string]$ApiId = "",
    [string]$ApiHash = "",
    [string]$BotUsername = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Set-EnvIfPresent {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [string]$Value = ""
    )
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        Set-Item -Path ("Env:{0}" -f $Key) -Value $Value
    }
}

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line.Length -eq 0 -or $line.StartsWith("#")) {
            return
        }
        $idx = $line.IndexOf("=")
        if ($idx -le 0) {
            return
        }
        $key = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if ($key.Length -gt 0 -and $value.Length -gt 0) {
            Set-Item -Path ("Env:{0}" -f $key) -Value $value
        }
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envFile = Join-Path $repoRoot ".env"
Import-DotEnv -Path $envFile

Set-EnvIfPresent -Key "TG_API_ID" -Value $ApiId
Set-EnvIfPresent -Key "TG_API_HASH" -Value $ApiHash
Set-EnvIfPresent -Key "TG_BOT_USERNAME" -Value $BotUsername

$tgApiId = [string]$env:TG_API_ID
$tgApiHash = [string]$env:TG_API_HASH
$tgBotUsername = [string]$env:TG_BOT_USERNAME
$telegramToken = [string]$env:TELEGRAM_TOKEN
$tgBotToken = [string]$env:TG_BOT_TOKEN

if ([string]::IsNullOrWhiteSpace($tgApiId)) {
    throw "Missing TG_API_ID. Set it in .env or pass -ApiId."
}
if ([string]::IsNullOrWhiteSpace($tgApiHash)) {
    throw "Missing TG_API_HASH. Set it in .env or pass -ApiHash."
}
if (
    [string]::IsNullOrWhiteSpace($tgBotUsername) -and
    [string]::IsNullOrWhiteSpace($telegramToken) -and
    [string]::IsNullOrWhiteSpace($tgBotToken)
) {
    throw "Missing bot identity. Set TG_BOT_USERNAME or TELEGRAM_TOKEN/TG_BOT_TOKEN."
}

$scriptPath = Join-Path $repoRoot "scripts\tg_mega_smoke.py"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Script not found: $scriptPath"
}

if ($DryRun) {
    Write-Host "Dry run:"
    Write-Host "  Repo: $repoRoot"
    Write-Host "  Python: $PythonExe"
    Write-Host "  TG_API_ID: $tgApiId"
    if (-not [string]::IsNullOrWhiteSpace($tgBotUsername)) {
        Write-Host "  TG_BOT_USERNAME: $tgBotUsername"
    } else {
        Write-Host "  TG_BOT_USERNAME: <auto-detect from token>"
    }
    Write-Host "  Command: `"$PythonExe`" `"$scriptPath`""
    exit 0
}

& $PythonExe $scriptPath
exit $LASTEXITCODE
