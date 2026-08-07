# Funding Arbitrage Terminal

Local FastAPI web application for research of a future delta-neutral Binance strategy:
LONG Spot plus SHORT USDT-M Perpetual.

Stage 1 imports a manual CSV/XLSX universe, checks Binance public metadata, stores mapped symbols
in local PostgreSQL, and manages capital/fee settings. Stage 2 adds realized Binance USD-M funding
history, current/last funding state, 7/14/30 day analytics, stability scoring, and funding-only
planning estimates.

## Windows Setup

Run these commands in PowerShell from the project root.

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Create a local PostgreSQL database:

```powershell
createdb -U postgres funding_terminal
```

Create `.env` from `.env.example` and set `DATABASE_URL`:

```powershell
Copy-Item .env.example .env
notepad .env
```

Example:

```text
DATABASE_URL=postgresql://postgres:password@127.0.0.1:5432/funding_terminal
```

Apply migrations and run checks:

```powershell
python -m funding_terminal migrate
python -m funding_terminal check-db
python -m funding_terminal check-binance
```

Funding analytics:

```powershell
python -m funding_terminal sync-funding --symbols BTC,ETH,ADA,SOL --days 30
python -m funding_terminal funding-status
python -m funding_terminal funding-report --window 14 --limit 20 --sort stability
```

Run the local app:

```powershell
python -m funding_terminal run
```

Open:

```text
http://127.0.0.1:8000
```

## Local Windows Setup

### First Run

From PowerShell:

```powershell
cd C:\Users\Lenovo\Desktop\Funding
.\scripts\setup_local.ps1
```

If `.env` contains `CHANGE_ME`, edit it and set your local PostgreSQL password:

```powershell
notepad .env
```

Then run setup again:

```powershell
.\scripts\setup_local.ps1
```

The setup script is idempotent. It checks Python, creates `.venv`, installs dependencies, checks
PostgreSQL, verifies `.env`, creates the `funding_terminal` database when credentials allow it,
applies migrations, checks Binance, runs tests, and prints application status.

### Normal Daily Start

Double-click:

```text
start_funding_terminal.bat
```

or run:

```powershell
.\start_funding_terminal.bat
```

The app binds to localhost only:

```text
http://127.0.0.1:8000
```

## Running The Application

Daily control is done with BAT files in the project root. They use `.venv\Scripts\python.exe`
directly and do not require PowerShell activation.

START:

```text
start_funding_terminal.bat
```

Starts the server in the background, prints its PID and URL, then exits after a short delay. Closing
the BAT window does not stop the server.

STOP:

```text
stop_funding_terminal.bat
```

Stops only the Funding Terminal process identified by its PID file, executable path, command line
when Windows exposes it, port, and health endpoint. It does not kill all `python.exe` processes.

RESTART:

```text
restart_funding_terminal.bat
```

Runs stop, waits for shutdown, then starts the terminal again as a detached background process.

STATUS:

```text
status_funding_terminal.bat
```

Shows process state, PID, HTTP health, URL, database status, and Binance status.

Funding CLI:

```text
python -m funding_terminal sync-funding [--days 30] [--symbols BTC,ETH] [--current-only] [--history-only]
python -m funding_terminal funding-status
python -m funding_terminal funding-report [--window 14] [--limit 20] [--sort stability]
```

Funding analytics uses realized Binance USD-M Futures funding payments from
`GET /fapi/v1/fundingRate`, current/last funding state from `GET /fapi/v1/premiumIndex`, and
funding interval overrides from `GET /fapi/v1/fundingInfo` when available. Rates are stored as
decimal fractions, so `0.0001` is displayed as `0.0100%`.

Web routes:

```text
/funding
/funding/{base_asset}
```

The 30d Gross Funding Estimate is a planning estimate based on Max Hedged Notional from the capital
model. It is not net profit; trading fees, basis, spread, slippage, and execution prices are not
included in Stage 2.

Master menu:

```text
funding_terminal.bat
```

The runtime manager keeps operational files here:

```text
runtime\funding_terminal.pid
logs\funding_terminal.log
logs\runtime_manager.log
```

If the PID file is stale, the runtime manager removes it. If a PID has been reused by another
process, STOP refuses to terminate it.

### Health Check

Run:

```powershell
.\check_funding_terminal.bat
```

It executes:

```powershell
.venv\Scripts\python.exe -m funding_terminal check-db
.venv\Scripts\python.exe -m funding_terminal check-binance
.venv\Scripts\python.exe -m funding_terminal status
```

## PostgreSQL Troubleshooting

PostgreSQL 18 default Windows tools are usually here:

```powershell
C:\Program Files\PostgreSQL\18\bin
```

Check service status:

```powershell
Get-Service postgresql-x64-18
```

Start service if needed:

```powershell
Start-Service postgresql-x64-18
```

Check readiness:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_isready.exe" -h 127.0.0.1 -p 5432
```

Wrong password:

- edit `.env`;
- replace `CHANGE_ME` in `DATABASE_URL`;
- do not add quotes around the URL unless your password requires URL escaping.

Database missing:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -h 127.0.0.1 -p 5432 -U postgres funding_terminal
```

Port 5432 unavailable:

```powershell
netstat -ano | findstr :5432
```

`DATABASE_URL` missing:

```powershell
Copy-Item .env.example .env
notepad .env
```

## CLI

```powershell
python -m funding_terminal migrate
python -m funding_terminal check-db
python -m funding_terminal check-binance
python -m funding_terminal import-universe .\imports\universe.csv
python -m funding_terminal refresh-universe
python -m funding_terminal status
python -m funding_terminal run
```

## Import Format

CSV:

```csv
Symbol
BTC
ETH
ADA
```

or:

```csv
Symbol,Enabled
BTC,1
ETH,1
ADA,0
```

XLSX uses the same columns. `BTCUSDT` is normalized to `BTC`. Non-USDT pairs such as
`ETHBTC` and `BTCUSDC` are rejected instead of guessed.

## Capital Model

Stage 1 stores a capital allocation model, not a hedge sizing model.

- Total Capital: all available USDT capital.
- Spot Budget: USDT allocated to buying Spot.
- Futures Margin Budget: USDT collateral allocated to USD-M Futures margin.
- Free Reserve: `Total Capital - Spot Budget - Futures Margin Budget`.
- Futures Capacity: `Futures Margin Budget * Futures Leverage`.
- Max Hedged Notional: `min(Spot Budget, Futures Capacity)`.

Stage 1 supports only `1x` and `2x` futures leverage. It does not calculate spot quantity,
futures quantity, hedge ratio, actual futures notional, PnL, or funding.

`Futures Margin Budget` is not futures notional. Funding in later stages will be calculated from
actual Futures Notional, not from Futures Margin Budget.

Default values:

- Total Capital: `4000 USDT`
- Spot Budget: `2000 USDT`
- Futures Margin Budget: `2000 USDT`
- Futures Leverage: `1x`

## Fee Model

Database fee values are decimal fractions. The source-of-truth is base fee plus discount rate:

- Spot Maker Base Fee: `0.001` = `0.1%`
- Spot Taker Base Fee: `0.001` = `0.1%`
- Futures Maker Base Fee: `0.0002` = `0.02%`
- Futures Taker Base Fee: `0.0005` = `0.05%`
- Fee Discount Rate: `0.45` = `45%`

Effective fees are derived:

```text
effective_fee = base_fee * (1 - fee_discount_rate)
```

With the defaults, effective fees are `0.055%`, `0.055%`, `0.011%`, and `0.0275%`.
Effective fees are not stored as source-of-truth, so the discount is not applied twice.

## Development Checks

```powershell
pytest
ruff check .
mypy src
```

## Stage 1 Scope

This stage intentionally does not implement funding analytics, current funding, basis/spread,
order book, liquidity, slippage, ranking, APR, expected PnL, leverage, liquidation, paper trading,
real trading, API keys, WebSockets, collectors, schedulers, notifications, or multi-exchange logic.
# Funding
