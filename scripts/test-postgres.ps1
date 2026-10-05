<#
.SYNOPSIS
  Run the full backend test suite against PostgreSQL (and Redis, if it is running).

.DESCRIPTION
  Uses DATABASE_URL from backend\.env; Django creates and drops a temporary
  "test_<name>" database, so your data is untouched (the DB user needs CREATEDB).
  If the Docker Redis container is healthy, Redis integration tests also run
  (against Redis database 15, never the one the app uses).

.EXAMPLE
  .\scripts\test-postgres.ps1
  .\scripts\test-postgres.ps1 -k security        # extra args go to pytest
#>
# Native tools (docker, python) write progress to stderr; Windows PowerShell 5.1 would turn that into
# terminating errors under 'Stop'. Exit codes are checked explicitly instead.
$ErrorActionPreference = 'Continue'
$backend = Resolve-Path (Join-Path $PSScriptRoot '..\backend')
$envFile = Join-Path $backend '.env'
$python = Join-Path $backend '.venv\Scripts\python.exe'

$dbLine = Get-Content $envFile | Where-Object { $_ -match '^DATABASE_URL=' } | Select-Object -First 1
if (-not $dbLine -or $dbLine -notmatch 'postgres') { throw 'DATABASE_URL in backend\.env must point at PostgreSQL.' }
$env:TEST_DATABASE_URL = $dbLine.Substring('DATABASE_URL='.Length)

$redis = docker inspect -f '{{.State.Health.Status}}' office-crm-redis-1 2>$null
if ($redis -eq 'healthy') {
    $env:TEST_REDIS_URL = 'redis://127.0.0.1:6379/15'
    Write-Host 'PostgreSQL + Redis integration tests' -ForegroundColor Cyan
} else {
    Remove-Item Env:TEST_REDIS_URL -ErrorAction SilentlyContinue
    Write-Host 'PostgreSQL (Redis not running: Redis integration tests will be skipped)' -ForegroundColor Yellow
}

Push-Location $backend
try {
    & $python -m pytest --create-db -rs @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
    Remove-Item Env:TEST_DATABASE_URL, Env:TEST_REDIS_URL -ErrorAction SilentlyContinue
}
