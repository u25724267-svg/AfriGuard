param(
    [string]$Language = "shona",
    [string]$Category = "H03",
    [string]$Severity = "S2"
)

$ErrorActionPreference = "Stop"

Write-Host "AfriGuard smoke test" -ForegroundColor Cyan
Write-Host "Language: $Language | Category: $Category | Severity: $Severity"

if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

Write-Host "Installing package and runtime dependencies..." -ForegroundColor Cyan
python -m pip install -r requirements.txt

Write-Host "Initializing database..." -ForegroundColor Cyan
afriguard bootstrap-db

Write-Host "Running dry generation check..." -ForegroundColor Cyan
afriguard generate --language $Language --category $Category --severity $Severity --n-prompts 1 --dry-run

Write-Host "Smoke test completed. Add OPENAI_API_KEY to .env before a real generation run." -ForegroundColor Green
