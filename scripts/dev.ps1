<#
.SYNOPSIS
  Start the whole development stack on Windows.

.DESCRIPTION
  1. Redis in Docker (docker-compose.yml), waiting until it is healthy
  2. Database migrations
  3. One PowerShell window each for: Django (API + WebSockets), Celery worker, Celery Beat, Vite frontend

  Close a window (or press Ctrl+C in it) to stop that process. Redis keeps running in Docker;
  stop it with:  docker compose down

.EXAMPLE
  .\scripts\dev.ps1
  .\scripts\dev.ps1 -SkipMigrate
#>
param(
    [switch]$SkipMigrate
)

# Native tools (docker, python) write progress to stderr; Windows PowerShell 5.1 would turn that into
# terminating errors under 'Stop'. Exit codes are checked explicitly instead.
$ErrorActionPreference = 'Continue'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
$celery = Join-Path $backend '.venv\Scripts\celery.exe'

if (-not (Test-Path $python)) { throw "Backend virtualenv not found. See README: Backend setup." }
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) { throw "Run 'npm install' in frontend first." }

# --- 1. Redis -------------------------------------------------------------
Write-Host '[1/3] Starting Redis (Docker)...' -ForegroundColor Cyan
docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host '      Docker engine not running; starting Docker Desktop...' -ForegroundColor Yellow
    docker desktop start --timeout 180 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop did not start. Open it manually, then re-run.' }
}
Push-Location $root
try { docker compose up -d redis 2>&1 | Out-Null } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed. Check: docker compose logs redis' }
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    $status = docker inspect -f '{{.State.Health.Status}}' office-crm-redis-1 2>$null
    if ($status -eq 'healthy') { $healthy = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $healthy) { throw 'Redis did not become healthy. Check: docker compose logs redis' }
Write-Host '      Redis is healthy on 127.0.0.1:6379' -ForegroundColor Green

# --- 2. Migrations --------------------------------------------------------
if (-not $SkipMigrate) {
    Write-Host '[2/3] Applying database migrations...' -ForegroundColor Cyan
    Push-Location $backend
    try {
        & $python manage.py migrate --noinput
        if ($LASTEXITCODE -ne 0) { throw 'Migrations failed (is PostgreSQL running?).' }
    } finally { Pop-Location }
}

# --- 3. Processes, one window each ---------------------------------------
Write-Host '[3/3] Opening windows: Django, Celery worker, Celery Beat, frontend' -ForegroundColor Cyan
function Start-Window($title, $dir, $command) {
    $script = "`$Host.UI.RawUI.WindowTitle = '$title'; Set-Location '$dir'; $command"
    Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $script | Out-Null
}
Start-Window 'CRM: Django' $backend "& '$python' manage.py runserver 127.0.0.1:8000"
Start-Window 'CRM: Celery worker' $backend "& '$celery' -A config worker --pool=solo -l info"
Start-Window 'CRM: Celery beat' $backend "& '$celery' -A config beat -l info"
Start-Window 'CRM: Frontend' $frontend 'npm run dev'

Write-Host ''
Write-Host 'Started. Open http://localhost:5173  (admin@office.test / Demo@12345 with demo data)' -ForegroundColor Green
Write-Host 'Health:   Administration > System status   or   http://localhost:5173/api/v1/health/'
