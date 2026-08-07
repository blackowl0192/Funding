# Stage 2 Funding Analytics

Stage 2 adds funding-only analytics for the existing LONG Spot plus SHORT USDT-M Perpetual
research workflow. It answers whether a symbol has historically paid positive funding with enough
stability to justify deeper Stage 3 analysis.

It does not estimate net profit. Basis, spread, slippage, executable prices, order book depth,
liquidity, fee deduction from strategy result, and trade recommendations are intentionally out of
scope until later stages.

## Binance Source Of Truth

Historical analytics use realized Binance USD-M Futures funding payments:

- `GET /fapi/v1/fundingRate`
- Official docs: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History

Current state uses the Binance premium index endpoint:

- `GET /fapi/v1/premiumIndex`
- Official docs: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price

Funding interval overrides are read when Binance exposes them:

- `GET /fapi/v1/fundingInfo`
- Official docs: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-Info

`lastFundingRate` from `premiumIndex` is stored and displayed as Current/Last Funding. It is not
used as historical source of truth and is not treated as guaranteed future funding.

## Units And Time

Binance rates are decimal fractions. The database stores `0.0001` for `0.0100%`. UI and CLI format
rates as percentages at display time.

All Binance millisecond timestamps are converted explicitly to timezone-aware UTC datetimes before
persistence. UI timestamps include the UTC suffix.

## Database

Migration `003_funding_analytics.sql` creates:

- `funding_events`: realized Binance funding payments with `UNIQUE(source, futures_symbol, funding_time)`.
- `funding_current`: latest current/last funding state per symbol.
- `funding_statistics`: cached 7/14/30 day analytics snapshots.
- `funding_sync_state`: history sync success/error metadata.

Events are stored indefinitely and sync is idempotent.

## Sync

`FundingHistoryService` loads realized funding history with `startTime`, `endTime`, and `limit`.
Pagination advances from the latest returned funding timestamp plus one millisecond and stops on
empty pages, short pages, non-advancing timestamps, or a fixed page cap.

First sync loads the requested history window, usually 30 days. Later syncs start from the latest
stored event minus a 12 hour overlap and rely on the unique event key to avoid duplicates.

`FundingCurrentService` uses the batch `premiumIndex` response for all symbols, then filters the
local eligible enabled universe. It does not make one request per symbol when the batch endpoint is
available.

## Metrics

For each 7d, 14d, and 30d window:

- event count
- mean funding
- median funding
- min/max funding
- cumulative funding
- Decimal-compatible standard deviation
- positive, negative, and zero counts
- positive and negative ratios
- average positive and average negative funding
- current and longest positive streaks
- current and longest negative streaks
- negative events in the last 24h and 3d
- estimated daily and 30d funding-only rate

Streaks are measured in consecutive funding events. If interval is known, UI can also show an
approximate duration.

## Interval And Estimates

Funding interval is not hardcoded. The system uses Binance `fundingInfo` when present. Otherwise it
detects the median interval from realized funding event timestamps.

If the interval appears to have changed, estimates use observed historical frequency:

```text
events_per_day = event_count / observed_history_days
```

Otherwise:

```text
events_per_day = 24 / funding_interval_hours
estimated_daily_rate = mean_rate * events_per_day
estimated_30d_rate = estimated_daily_rate * 30
```

The 30d Gross Funding Estimate is a planning value:

```text
gross_funding_estimate_30d = max_hedged_notional * estimated_30d_rate
```

It uses Max Hedged Notional from the capital model, not Total Capital and not Futures Margin Budget.
Trading fees are not included yet.

## Stability Score

Funding Stability Score is 0-100 and measures persistence, not yield:

- positive persistence: 40 points from positive ratio
- stability: 20 points from low volatility relative to mean/median scale
- negative streak control: 5 points from short longest negative streak
- current positive streak: 15 points from sustained current positive run
- median quality: 10 points when median and mean are positive
- data quality: 10 points from GOOD/PARTIAL/STALE/INSUFFICIENT

High one-off funding spikes are not directly rewarded; volatility and negative streaks reduce the
score.

## Data Quality

Data quality values:

- `GOOD`: broad coverage, expected event count, recent latest event, no large gap.
- `PARTIAL`: usable but incomplete coverage, changed interval, or large gaps.
- `INSUFFICIENT`: empty history, one event, or too little coverage.
- `STALE`: latest event is older than a conservative freshness threshold.

Recently listed or inactive symbols naturally become PARTIAL or INSUFFICIENT until enough events
exist.

## Trend And Warnings

Trend compares mean funding in the last 7 days against the previous 7 days with a tolerance:

- `IMPROVING`
- `STABLE`
- `DETERIORATING`
- `UNKNOWN`

`REVERSAL_RISK` is informational only. It can appear when a mostly positive 14d history has recent
negative events or a current negative streak. It is not an automated trading signal.

## CLI

```powershell
python -m funding_terminal sync-funding --days 30
python -m funding_terminal sync-funding --symbols BTC,ETH,ADA,SOL --days 30
python -m funding_terminal sync-funding --current-only
python -m funding_terminal sync-funding --history-only
python -m funding_terminal funding-status
python -m funding_terminal funding-report --window 14 --limit 20 --sort stability
```

## Web UI

Routes:

- `/funding`: funding analytics dashboard with Refresh Funding Data.
- `/funding/{base_asset}`: symbol funding detail, 7/14/30 metrics, current state, and 30d history.
- `/symbols`: extended with Current/Last Funding, 14d metrics, 30d estimate, data quality, and links
  to symbol funding detail.

## Limitations

Stage 2 is funding-only. It does not know actual execution price, quantity, basis, spread, slippage,
or complete trading cost impact. Those remain for Stage 3 and Stage 4.
