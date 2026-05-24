# Bootstrap mullen_ai_jarvis on a fresh Windows workstation.
# Run from F:\Projects\mullen_ai_jarvis\

param(
    [switch]$SkipPostgres,
    [switch]$SkipOllama
)

$ErrorActionPreference = "Stop"

Write-Host "==> mullen_ai_jarvis bootstrap" -ForegroundColor Cyan

# 1. Python venv
if (-not (Test-Path ".\backend\.venv")) {
    Write-Host "Creating Python venv..."
    python -m venv .\backend\.venv
}
& .\backend\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\backend\.venv\Scripts\python.exe -m pip install -e .\backend[dev]

# 2. .env
if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
    Write-Host "Created .env from example. Edit before running." -ForegroundColor Yellow
}

# 3. Postgres reminder (no automatic install)
if (-not $SkipPostgres) {
    Write-Host ""
    Write-Host "Postgres + pgvector required. If not installed:" -ForegroundColor Yellow
    Write-Host "  1. Install PostgreSQL 16 from https://www.postgresql.org/download/windows/"
    Write-Host "  2. In psql: CREATE DATABASE jarvis; CREATE EXTENSION vector;"
    Write-Host "  3. Adjust DATABASE_URL in .env"
}

# 4. Ollama reminder
if (-not $SkipOllama) {
    Write-Host ""
    Write-Host "Ollama required for local LLM. If not installed:" -ForegroundColor Yellow
    Write-Host "  1. Download from https://ollama.com/download/windows"
    Write-Host "  2. ollama pull llama3.1:8b"
}

Write-Host ""
Write-Host "==> Bootstrap complete." -ForegroundColor Green
Write-Host "Start the API:  .\backend\.venv\Scripts\uvicorn.exe app.main:app --reload --app-dir backend"
