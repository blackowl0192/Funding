$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EnvPath = Join-Path $ProjectRoot ".env"
$EnvExamplePath = Join-Path $ProjectRoot ".env.example"
$PgBin = "C:\Program Files\PostgreSQL\18\bin"
$PsqlExe = Join-Path $PgBin "psql.exe"
$CreatedbExe = Join-Path $PgBin "createdb.exe"
$PgIsReadyExe = Join-Path $PgBin "pg_isready.exe"

Set-Location $ProjectRoot

function Write-Step($Message) {
    Write-Host ""
    Write-Host "== $Message =="
}

function Get-EnvValue($Name) {
    if (-not (Test-Path -LiteralPath $EnvPath)) {
        return $null
    }
    $line = Get-Content -LiteralPath $EnvPath | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
    if (-not $line) {
        return $null
    }
    return $line.Substring($Name.Length + 1)
}

function Assert-DatabaseUrlConfigured {
    $databaseUrl = Get-EnvValue "DATABASE_URL"
    if ([string]::IsNullOrWhiteSpace($databaseUrl) -or $databaseUrl -match "CHANGE_ME") {
        Write-Host "DATABASE_URL is not configured."
        Write-Host "Edit .env and replace CHANGE_ME with your local PostgreSQL password."
        Write-Host "Then run this script again."
        exit 1
    }
    return $databaseUrl
}

function Find-PostgresBin {
    if (Test-Path -LiteralPath $PgIsReadyExe) {
        return
    }

    $installRoot = "C:\Program Files\PostgreSQL"
    if (-not (Test-Path -LiteralPath $installRoot)) {
        throw "PostgreSQL was not found under C:\Program Files\PostgreSQL."
    }

    $versionDir = Get-ChildItem -LiteralPath $installRoot -Directory |
        Sort-Object Name -Descending |
        Select-Object -First 1

    if (-not $versionDir) {
        throw "No PostgreSQL version directory was found."
    }

    $script:PgBin = Join-Path $versionDir.FullName "bin"
    $script:PsqlExe = Join-Path $script:PgBin "psql.exe"
    $script:CreatedbExe = Join-Path $script:PgBin "createdb.exe"
    $script:PgIsReadyExe = Join-Path $script:PgBin "pg_isready.exe"
}

function Ensure-Database {
    param([string]$DatabaseUrl)

    $uri = [Uri]$DatabaseUrl
    $userInfo = $uri.UserInfo.Split(":", 2)
    $dbUser = [Uri]::UnescapeDataString($userInfo[0])
    $dbPassword = if ($userInfo.Length -gt 1) { [Uri]::UnescapeDataString($userInfo[1]) } else { "" }
    $dbName = $uri.AbsolutePath.TrimStart("/")
    $dbHost = $uri.Host
    $dbPort = if ($uri.Port -gt 0) { $uri.Port } else { 5432 }

    $env:PGPASSWORD = $dbPassword
    try {
        & $PsqlExe -w -h $dbHost -p $dbPort -U $dbUser -d $dbName -Atc "SELECT 1" *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Database '$dbName' exists and is reachable."
            return
        }

        Write-Host "Database '$dbName' is not reachable. Trying to create it if missing..."
        & $CreatedbExe -w -h $dbHost -p $dbPort -U $dbUser $dbName
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create database '$dbName'. Check PostgreSQL password and privileges."
        }
    }
    finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    }
}

Write-Step "Python"
python --version

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Step "Creating .venv"
    python -m venv .venv
}

Write-Step "Installing dependencies"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e ".[dev]"
& $PythonExe --version

Write-Step "PostgreSQL"
Find-PostgresBin
& $PgIsReadyExe -h 127.0.0.1 -p 5432
$pgService = Get-Service | Where-Object { $_.Name -like "*postgres*" -or $_.DisplayName -like "*postgres*" } | Select-Object -First 1
if ($pgService) {
    Write-Host "Service: $($pgService.Name) / $($pgService.Status)"
    if ($pgService.Status -ne "Running") {
        Write-Host "Trying to start PostgreSQL service..."
        Start-Service -Name $pgService.Name
    }
}
else {
    Write-Host "PostgreSQL service was not found."
}

Write-Step ".env"
if (-not (Test-Path -LiteralPath $EnvPath)) {
    if (Test-Path -LiteralPath $EnvExamplePath) {
        Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    }
    else {
        @"
APP_HOST=127.0.0.1
APP_PORT=8000
APP_DEBUG=false

DATABASE_URL=postgresql://postgres:CHANGE_ME@127.0.0.1:5432/funding_terminal

BINANCE_SPOT_BASE_URL=https://api.binance.com
BINANCE_FUTURES_BASE_URL=https://fapi.binance.com
BINANCE_HTTP_TIMEOUT_SECONDS=10
IMPORT_MAX_ROWS=1000
LOG_LEVEL=INFO
"@ | Set-Content -LiteralPath $EnvPath -Encoding UTF8
    }
    Write-Host ".env was created. Configure DATABASE_URL before continuing."
}

$databaseUrl = Assert-DatabaseUrlConfigured

Write-Step "Database"
Ensure-Database -DatabaseUrl $databaseUrl
& $PythonExe -m funding_terminal check-db
& $PythonExe -m funding_terminal migrate
& $PythonExe -m funding_terminal check-db

Write-Step "Binance"
& $PythonExe -m funding_terminal check-binance

Write-Step "Quality checks"
& $PythonExe -m pytest
& $PythonExe -m ruff check .
& $PythonExe -m mypy src

Write-Step "Status"
& $PythonExe -m funding_terminal status

Write-Host ""
Write-Host "Setup complete. Start the app with:"
Write-Host ".\start_funding_terminal.bat"

