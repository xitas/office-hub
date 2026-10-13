<#
.SYNOPSIS
  Run the full backend test suite against PostgreSQL (and Redis, if it is running), with the local venv.

.DESCRIPTION
  The quick native run. It uses the same test settings as CI: TEST_DATABASE_URL and TEST_REDIS_URL only
  (tests never read backend\.env), the same pytest options, and Redis database 15.
  It warns when your Python or packages differ from CI's (the image in docker-compose.test.yml and
  backend\requirements.lock). For an exact CI run, use .\scripts\test-ci.ps1.

  DATABASE_URL in backend\.env gives the server; Django creates and drops a temporary "test_<name>"
  database, so your data is untouched (the DB user needs CREATEDB).

.EXAMPLE
  .\scripts\test-postgres.ps1
  .\scripts\test-postgres.ps1 -k security        # extra args go to pytest
#>
# Native tools (docker, python) write progress to stderr; Windows PowerShell 5.1 would turn that into
# terminating errors under 'Stop'. Exit codes are checked explicitly instead.
$ErrorActionPreference = 'Continue'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$backend = Join-Path $root 'backend'
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

# Same Python and packages as CI? (Differences can make a run pass here and fail there.)
$ciImage = (Select-String -Path (Join-Path $root 'docker-compose.test.yml') -Pattern 'image:\s*python:(\S+?)(-slim)?\s*$').Matches[0].Groups[1].Value
$localPython = (& $python -c 'import platform; print(platform.python_version())').Trim()
if ($ciImage -and $localPython -ne $ciImage) {
    Write-Host "Note: local Python $localPython, CI uses $ciImage. For an exact CI run: .\scripts\test-ci.ps1" -ForegroundColor Yellow
}
$locked = @{}
Get-Content (Join-Path $backend 'requirements.lock') | Where-Object { $_ -match '^([^#=]+)==(.+)$' } | ForEach-Object {
    $locked[$Matches[1].ToLower().Replace('_', '-')] = $Matches[2].Trim()
}
$drift = & $python -m pip freeze 2>$null | Where-Object { $_ -match '^([^=]+)==(.+)$' } | ForEach-Object {
    $name = $Matches[1].ToLower().Replace('_', '-')
    if ($locked.ContainsKey($name) -and $locked[$name] -ne $Matches[2].Trim()) { "$name $($Matches[2].Trim()) (CI: $($locked[$name]))" }
}
if ($drift) {
    Write-Host "Note: packages differ from requirements.lock: $($drift -join ', ')" -ForegroundColor Yellow
    Write-Host '      Match CI with: backend\.venv\Scripts\pip install -r backend\requirements-dev.txt -c backend\requirements.lock' -ForegroundColor Yellow
}

Push-Location $backend
try {
    & $python -m pytest --create-db -rs -p no:cacheprovider @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
    Remove-Item Env:TEST_DATABASE_URL, Env:TEST_REDIS_URL -ErrorAction SilentlyContinue
}
