<#
.SYNOPSIS
  Run the backend tests and the dependency audit exactly as CI does (docker-compose.test.yml), so "passes here"
  means "passes in CI".

.DESCRIPTION
  Same containers as the GitHub Actions job: the pinned Python image, the packages in
  backend\requirements.lock, PostgreSQL 17 and Redis (throwaway, no host ports), no backend\.env,
  UTC clock. Then the dependency audit (the compose "audit" service, which holds the documented advisory
  exceptions). Needs Docker Desktop. The first run downloads the images and packages; later runs reuse them.

.PARAMETER Lock
  Regenerate backend\requirements.lock from requirements*.txt inside the same image (after changing them).

.EXAMPLE
  .\scripts\test-ci.ps1
  .\scripts\test-ci.ps1 -k chat           # extra args go to pytest
  .\scripts\test-ci.ps1 -Lock
#>
param([switch]$Lock, [Parameter(ValueFromRemainingArguments = $true)][string[]]$PytestArgs)
# Native tools write progress to stderr; exit codes are checked explicitly instead.
$ErrorActionPreference = 'Continue'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$compose = Join-Path $root 'docker-compose.test.yml'

docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running. Start Docker Desktop first.' }

try {
    if ($Lock) {
        $header = @(
            '# Exact versions the tests run with, in CI and locally (pip install -r requirements-dev.txt -c requirements.lock).',
            '# Regenerate after changing requirements*.txt:  .\scripts\test-ci.ps1 -Lock'
        )
        $frozen = docker compose -f $compose run --rm --no-deps --entrypoint sh tests -c 'pip install -q -r requirements-dev.txt && pip freeze'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        $lockFile = Join-Path $root 'backend\requirements.lock'
        [IO.File]::WriteAllLines($lockFile, [string[]]($header + ($frozen | Where-Object { $_ -match '==' })))
        Write-Host "Updated $lockFile" -ForegroundColor Green
        exit 0
    }
    docker compose -f $compose run --rm tests @PytestArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host 'Dependency audit' -ForegroundColor Cyan
    docker compose -f $compose run --rm --no-deps audit
    exit $LASTEXITCODE
} finally {
    docker compose -f $compose down -v *> $null
}
