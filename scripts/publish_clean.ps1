param(
    [switch]$AllowDirty
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

Write-Host "== publish-clean checks ==" -ForegroundColor Cyan

function Fail([string]$Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    exit 1
}

function Warn([string]$Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Ok([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

$statusLines = @(git status --porcelain)
if ($statusLines.Count -gt 0 -and -not $AllowDirty) {
    Write-Host "Working tree is not clean:" -ForegroundColor Red
    $statusLines | ForEach-Object { Write-Host "  $_" }
    Fail "Commit/stash changes first, or run with -AllowDirty."
}
if ($statusLines.Count -gt 0) {
    Warn "Working tree is dirty, but continuing due to -AllowDirty."
} else {
    Ok "Working tree is clean."
}

$tracked = @(git ls-files)
$forbiddenTracked = @(
    ".env",
    "billing_details.txt"
)
foreach ($item in $forbiddenTracked) {
    if ($tracked -contains $item) {
        Fail "Forbidden tracked file detected: $item"
    }
}
Ok "No forbidden tracked local-secret files."

$forbiddenPrefixes = @(".sessions/", ".data/", "local_obsidian_inbox/")
foreach ($prefix in $forbiddenPrefixes) {
    $hit = $tracked | Where-Object { $_.StartsWith($prefix) } | Select-Object -First 1
    if ($null -ne $hit) {
        Fail "Forbidden tracked runtime path detected: $hit"
    }
}
Ok "No tracked runtime/session directories."

$secretPattern = "(TELEGRAM_TOKEN=[0-9]{8,10}:[A-Za-z0-9_-]{20,}|GEMINI_API_KEY=AIza[0-9A-Za-z\-_]{20,}|CF_TUNNEL_TOKEN=eyJ[A-Za-z0-9_\-\.=]+|[0-9]{8,10}:[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z\-_]{20,})"
$secretHits = @(
    git grep -n -I -E $secretPattern -- . `
        ":(exclude).env.example" `
        ":(exclude)billing_details.example.txt" `
        ":(exclude)OPEN_SOURCE_CHECKLIST.md"
)
if ($secretHits.Count -gt 0) {
    Write-Host "Potential secret leaks in tracked files:" -ForegroundColor Red
    $secretHits | ForEach-Object { Write-Host "  $_" }
    Fail "Secret-like values found."
}
Ok "No secret-like values found in tracked files."

$pathPattern = "C:\\Users\\|/home/[^/]+/"
$pathHits = @(
    git grep -n -I -E $pathPattern -- . `
        ":(exclude)README.md" `
        ":(exclude)RUNBOOK.md" `
        ":(exclude)DEPLOYMENT_CHECKLIST.md" `
        ":(exclude)INCIDENT_PLAYBOOK.md" `
        ":(exclude)OPEN_SOURCE_CHECKLIST.md" `
        ":(exclude)deploy/systemd/*"
)
if ($pathHits.Count -gt 0) {
    Warn "Local path patterns found outside allowed docs:"
    $pathHits | ForEach-Object { Write-Host "  $_" }
} else {
    Ok "No local path patterns outside docs."
}

Write-Host ""
Write-Host "publish-clean passed. Safe to push template branch." -ForegroundColor Green
Write-Host "Next: git push origin <branch>"
