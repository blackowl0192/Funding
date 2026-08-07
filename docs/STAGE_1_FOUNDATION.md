# Stage 1 Foundation

## Goal

Stage 1 creates a local foundation for researching a future Binance funding arbitrage workflow:
LONG Spot plus SHORT USDT-M Perpetual. It does not trade and it does not use API keys.

The user can:

- run PostgreSQL locally;
- migrate the database;
- run the FastAPI app;
- upload a manual CSV/XLSX universe;
- validate Spot and USD-M Perpetual availability through Binance public metadata;
- enable or disable watchlist symbols;
- edit capital and fee assumptions.

## Architecture

The project is a modular monolith under `src/funding_terminal`.

- `domain`: dataclasses, enums, and domain errors. It has no FastAPI, PostgreSQL, or HTML imports.
- `exchange`: Binance public REST adapter and metadata parser.
- `services`: use cases for import, universe refresh, and settings validation.
- `repositories`: PostgreSQL persistence only. Repositories do not compute eligibility.
- `db`: asyncpg connection and versioned SQL migration runner.
- `web`: FastAPI routes, Jinja2 templates, static CSS/JS.
- `config`: pydantic-settings based configuration.

Domain models use `dataclass(frozen=True)` because Stage 1 data is mostly immutable business state
passed between services. Pydantic is used for configuration and web boundary parsing.

## Database Schema

`symbols` stores one Binance row per base asset:

- `base_asset`
- `spot_symbol`, `futures_symbol`
- `spot_status`, `futures_status`
- `mapping_status`, `mapping_reason`
- `strategy_eligible`
- `enabled`
- timestamps

`import_runs` stores import summaries and failures.

`trading_settings` is a singleton typed settings table with `id = 1`. Migration 002 replaces the
old effective-fee-only model with capital allocation plus base fee and discount source values.

`schema_migrations` is managed by the custom migration runner.

## Migrations

Migrations live in `migrations/*.sql` and are sorted by numeric prefix.

Run:

```powershell
python -m funding_terminal migrate
```

The runner applies only missing migrations, wraps each file in a transaction, and records the
applied version.

## Import Format

Supported file types:

- CSV
- XLSX

Required column:

- `Symbol`

Optional column:

- `Enabled`

Accepted examples:

```csv
Symbol
BTC
ETH
ADA
```

```csv
Symbol,Enabled
BTC,1
ETH,1
ADA,0
```

## Normalization

Rules:

- trim whitespace;
- uppercase;
- remove BOM;
- remove surrounding quotes;
- remove a final `USDT` from inputs like `BTCUSDT`;
- skip blank rows;
- remove duplicates;
- reject invalid symbols and non-USDT pairs.

Examples:

- `btc` -> `BTC`
- `BTCUSDT` -> `BTC`
- `ETHBTC` -> rejected
- `BTCUSDC` -> rejected

## Binance Endpoints

Stage 1 uses only official public REST metadata:

- Spot exchangeInfo: `GET https://api.binance.com/api/v3/exchangeInfo`
- USD-M Futures exchangeInfo: `GET https://fapi.binance.com/fapi/v1/exchangeInfo`
- Spot health: `GET https://api.binance.com/api/v3/time`
- Futures health: `GET https://fapi.binance.com/fapi/v1/time`

HTTP requests use `httpx.AsyncClient`, bounded retries for safe GET requests, and no API keys.

## Eligibility Rules

For imported `BASE`, expected symbols are:

- Spot: `BASEUSDT`
- Futures: `BASEUSDT`

Eligible means:

- Spot symbol exists;
- Spot status is `TRADING`;
- Spot quote asset is `USDT`;
- Spot base asset matches input;
- Spot trading is allowed when the metadata flag is present;
- Futures symbol exists;
- Futures status is `TRADING`;
- Futures quote asset is `USDT`;
- Futures margin asset is `USDT`;
- Futures contract type is `PERPETUAL`;
- Futures base asset matches input.

The app loads Spot exchangeInfo once and Futures exchangeInfo once per import or refresh. It does
not make per-symbol Binance requests.

## Mapping Statuses

- `MATCHED`
- `SPOT_MISSING`
- `FUTURES_MISSING`
- `SPOT_INACTIVE`
- `FUTURES_INACTIVE`
- `UNSUPPORTED_SPOT`
- `UNSUPPORTED_FUTURES`
- `METADATA_MISMATCH`
- `INVALID_INPUT`
- `ERROR`

`strategy_eligible` is true only for `MATCHED`.

## Capital Model

Stage 1 models capital capacities only. It does not calculate executable quantities or actual hedge
size.

- Total Capital: all available capital.
- Spot Budget: USDT allocated to buying Spot.
- Futures Margin Budget: USDT collateral allocated to USD-M Futures.
- Free Reserve: `Total Capital - Spot Budget - Futures Margin Budget`.
- Futures Capacity: `Futures Margin Budget * Futures Leverage`.
- Max Hedged Notional: `min(Spot Budget, Futures Capacity)`.
- Capital Utilization: `(Spot Budget + Futures Margin Budget) / Total Capital`.

Stage 1 supports only `1x` and `2x` leverage. `Futures Margin Budget` is not Futures Notional.
Funding in future stages will be calculated from actual Futures Notional, not from Futures Margin
Budget.

Examples:

- `4000 / 2000 / 2000 / 1x` gives `Free Reserve = 0`, `Futures Capacity = 2000`,
  `Max Hedged Notional = 2000`.
- `4000 / 2500 / 1500 / 2x` gives `Free Reserve = 0`, `Futures Capacity = 3000`,
  `Max Hedged Notional = 2500`.

## Fee Model

Database base fees and discount are decimal fractions. UI fields are percentages.

- Spot Maker Base Fee: DB `0.001` = UI `0.1%`
- Spot Taker Base Fee: DB `0.001` = UI `0.1%`
- Futures Maker Base Fee: DB `0.0002` = UI `0.02%`
- Futures Taker Base Fee: DB `0.0005` = UI `0.05%`
- Fee Discount Rate: DB `0.45` = UI `45%`

Effective fees are derived:

```text
effective_fee = base_fee * (1 - fee_discount_rate)
```

With defaults:

- Spot maker effective: `0.055%`
- Spot taker effective: `0.055%`
- Futures maker effective: `0.011%`
- Futures taker effective: `0.0275%`

Effective fees are not stored as source-of-truth. This prevents applying the discount twice when
the discount changes.

## Web Routes

- `GET /`: dashboard
- `GET /health`: JSON dependency status
- `GET /import`: upload page
- `POST /import`: CSV/XLSX import
- `GET /symbols`: symbols table with search, filters, sorting, pagination
- `POST /symbols/{base_asset}/enable`: enable one symbol
- `POST /symbols/{base_asset}/disable`: disable one symbol
- `POST /symbols/{base_asset}/refresh`: refresh one symbol from current Binance metadata
- `POST /symbols/refresh-all`: refresh all imported symbols
- `GET /settings`: settings page
- `POST /settings`: update settings

HTMX improves table updates and forms, but normal navigation remains available.

## CLI

- `python -m funding_terminal migrate`
- `python -m funding_terminal check-db`
- `python -m funding_terminal check-binance`
- `python -m funding_terminal import-universe path/to/file.xlsx`
- `python -m funding_terminal refresh-universe`
- `python -m funding_terminal status`
- `python -m funding_terminal run`

## Known Limitations

- Localhost only by default.
- No authentication in Stage 1.
- No real trading, private endpoints, API keys, or WebSockets.
- No automatic symbol discovery.
- Repository tests use fakes unless a local PostgreSQL test strategy is added later.

## Stage 2

Stage 2 can add `FundingHistoryService` and `FundingAnalyticsService` without changing the Stage 1
domain boundaries. Funding data, rankings, scores, and APR calculations are intentionally absent
from Stage 1.
