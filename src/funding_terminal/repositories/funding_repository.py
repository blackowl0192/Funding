from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from funding_terminal.db.database import Database
from funding_terminal.domain.funding import (
    ZERO,
    DataQuality,
    FundingCurrent,
    FundingEvent,
    FundingStatistics,
    FundingStatusSummary,
    FundingSymbol,
    FundingSyncState,
    FundingTableRow,
    FundingTrend,
    planning_funding_income_30d,
)
from funding_terminal.domain.models import TradingSettings

WINDOW_DAYS = (7, 14, 30)
FUNDING_SORT_COLUMNS = {
    "base_asset": "s.base_asset",
    "current": "COALESCE(c.last_funding_rate, 0)",
    "mean": "COALESCE(st.mean_rate, 0)",
    "positive_ratio": "COALESCE(st.positive_ratio, 0)",
    "stability": "COALESCE(st.stability_score, 0)",
    "cumulative": "COALESCE(st.cumulative_rate, 0)",
    "estimate": "COALESCE(st30.estimated_30d_rate, 0)",
    "current_streak": "COALESCE(st.current_positive_streak, 0)",
    "updated": "COALESCE(c.updated_at, ss.last_success_at, st.calculated_at)",
}


class FundingEventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_events(self, events: Sequence[FundingEvent]) -> tuple[int, int]:
        inserted = 0
        existing = 0
        for event in events:
            row_id = await self._db.fetchval(
                """
                INSERT INTO funding_events (
                    symbol_id,
                    futures_symbol,
                    funding_time,
                    funding_rate,
                    mark_price,
                    source
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (source, futures_symbol, funding_time) DO NOTHING
                RETURNING id
                """,
                event.symbol_id,
                event.futures_symbol,
                event.funding_time,
                event.funding_rate,
                event.mark_price,
                event.source,
            )
            if row_id is None:
                existing += 1
            else:
                inserted += 1
        return inserted, existing

    async def latest_event(self, symbol_id: int) -> FundingEvent | None:
        row = await self._db.fetchrow(
            """
            SELECT symbol_id, futures_symbol, funding_time, funding_rate, mark_price, source
            FROM funding_events
            WHERE symbol_id = $1
            ORDER BY funding_time DESC
            LIMIT 1
            """,
            symbol_id,
        )
        return _event_from_row(row) if row is not None else None

    async def list_events(
        self,
        symbol_id: int,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[FundingEvent, ...]:
        clauses = ["symbol_id = $1"]
        params: list[object] = [symbol_id]
        if start_at is not None:
            params.append(start_at)
            clauses.append(f"funding_time >= ${len(params)}")
        if end_at is not None:
            params.append(end_at)
            clauses.append(f"funding_time <= ${len(params)}")
        limit_sql = ""
        if limit is not None:
            params.append(limit)
            limit_sql = f"LIMIT ${len(params)}"
        rows = await self._db.fetch(
            f"""
            SELECT symbol_id, futures_symbol, funding_time, funding_rate, mark_price, source
            FROM funding_events
            WHERE {" AND ".join(clauses)}
            ORDER BY funding_time ASC
            {limit_sql}
            """,
            *params,
        )
        return tuple(_event_from_row(row) for row in rows)


class FundingCurrentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_many(self, items: Sequence[FundingCurrent]) -> int:
        if not items:
            return 0
        await self._db.executemany(
            """
            INSERT INTO funding_current (
                symbol_id,
                futures_symbol,
                mark_price,
                index_price,
                last_funding_rate,
                next_funding_time,
                interest_rate,
                funding_interval_hours,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
            ON CONFLICT (symbol_id) DO UPDATE SET
                futures_symbol = EXCLUDED.futures_symbol,
                mark_price = EXCLUDED.mark_price,
                index_price = EXCLUDED.index_price,
                last_funding_rate = EXCLUDED.last_funding_rate,
                next_funding_time = EXCLUDED.next_funding_time,
                interest_rate = EXCLUDED.interest_rate,
                funding_interval_hours = EXCLUDED.funding_interval_hours,
                updated_at = NOW()
            """,
            tuple(
                (
                    item.symbol_id,
                    item.futures_symbol,
                    item.mark_price,
                    item.index_price,
                    item.last_funding_rate,
                    item.next_funding_time,
                    item.interest_rate,
                    item.funding_interval_hours,
                )
                for item in items
            ),
        )
        return len(items)

    async def get(self, symbol_id: int) -> FundingCurrent | None:
        row = await self._db.fetchrow(
            """
            SELECT symbol_id,
                   futures_symbol,
                   mark_price,
                   index_price,
                   last_funding_rate,
                   next_funding_time,
                   interest_rate,
                   funding_interval_hours,
                   updated_at
            FROM funding_current
            WHERE symbol_id = $1
            """,
            symbol_id,
        )
        return _current_from_row(row) if row is not None else None


class FundingStatisticsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_many(self, items: Sequence[FundingStatistics]) -> int:
        if not items:
            return 0
        await self._db.executemany(
            """
            INSERT INTO funding_statistics (
                symbol_id,
                window_days,
                calculated_at,
                event_count,
                first_event_at,
                last_event_at,
                mean_rate,
                median_rate,
                min_rate,
                max_rate,
                stddev_rate,
                cumulative_rate,
                positive_count,
                negative_count,
                zero_count,
                positive_ratio,
                negative_ratio,
                current_positive_streak,
                longest_positive_streak,
                current_negative_streak,
                longest_negative_streak,
                average_positive_rate,
                average_negative_rate,
                funding_interval_hours,
                estimated_events_per_day,
                estimated_daily_rate,
                estimated_30d_rate,
                negative_events_last_24h,
                negative_events_last_3d,
                stability_score,
                trend,
                reversal_warning,
                data_quality
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,
                $31, $32, $33
            )
            ON CONFLICT (symbol_id, window_days) DO UPDATE SET
                calculated_at = EXCLUDED.calculated_at,
                event_count = EXCLUDED.event_count,
                first_event_at = EXCLUDED.first_event_at,
                last_event_at = EXCLUDED.last_event_at,
                mean_rate = EXCLUDED.mean_rate,
                median_rate = EXCLUDED.median_rate,
                min_rate = EXCLUDED.min_rate,
                max_rate = EXCLUDED.max_rate,
                stddev_rate = EXCLUDED.stddev_rate,
                cumulative_rate = EXCLUDED.cumulative_rate,
                positive_count = EXCLUDED.positive_count,
                negative_count = EXCLUDED.negative_count,
                zero_count = EXCLUDED.zero_count,
                positive_ratio = EXCLUDED.positive_ratio,
                negative_ratio = EXCLUDED.negative_ratio,
                current_positive_streak = EXCLUDED.current_positive_streak,
                longest_positive_streak = EXCLUDED.longest_positive_streak,
                current_negative_streak = EXCLUDED.current_negative_streak,
                longest_negative_streak = EXCLUDED.longest_negative_streak,
                average_positive_rate = EXCLUDED.average_positive_rate,
                average_negative_rate = EXCLUDED.average_negative_rate,
                funding_interval_hours = EXCLUDED.funding_interval_hours,
                estimated_events_per_day = EXCLUDED.estimated_events_per_day,
                estimated_daily_rate = EXCLUDED.estimated_daily_rate,
                estimated_30d_rate = EXCLUDED.estimated_30d_rate,
                negative_events_last_24h = EXCLUDED.negative_events_last_24h,
                negative_events_last_3d = EXCLUDED.negative_events_last_3d,
                stability_score = EXCLUDED.stability_score,
                trend = EXCLUDED.trend,
                reversal_warning = EXCLUDED.reversal_warning,
                data_quality = EXCLUDED.data_quality
            """,
            tuple(_statistics_args(item) for item in items),
        )
        return len(items)

    async def list_by_symbol(self, symbol_id: int) -> tuple[FundingStatistics, ...]:
        rows = await self._db.fetch(
            """
            SELECT *
            FROM funding_statistics
            WHERE symbol_id = $1
            ORDER BY window_days
            """,
            symbol_id,
        )
        statistics: list[FundingStatistics] = []
        for row in rows:
            item = _statistics_from_row(row)
            if item is not None:
                statistics.append(item)
        return tuple(statistics)

    async def list_table_rows(
        self,
        settings: TradingSettings,
        *,
        window_days: int = 14,
        sort: str = "stability",
        direction: str = "desc",
        limit: int = 200,
    ) -> tuple[FundingTableRow, ...]:
        order_column = FUNDING_SORT_COLUMNS.get(sort, FUNDING_SORT_COLUMNS["stability"])
        order_direction = "ASC" if direction.lower() == "asc" else "DESC"
        rows = await self._db.fetch(
            f"""
            SELECT s.id AS symbol_id,
                   s.base_asset,
                   s.futures_symbol,
                   c.symbol_id AS current_symbol_id,
                   c.futures_symbol AS current_futures_symbol,
                   c.mark_price,
                   c.index_price,
                   c.last_funding_rate,
                   c.next_funding_time,
                   c.interest_rate,
                   c.funding_interval_hours AS current_interval_hours,
                   c.updated_at AS current_updated_at,
                   st.*,
                   st7.id AS st7_id,
                   st7.symbol_id AS st7_symbol_id,
                   st7.window_days AS st7_window_days,
                   st7.calculated_at AS st7_calculated_at,
                   st7.event_count AS st7_event_count,
                   st7.first_event_at AS st7_first_event_at,
                   st7.last_event_at AS st7_last_event_at,
                   st7.mean_rate AS st7_mean_rate,
                   st7.median_rate AS st7_median_rate,
                   st7.min_rate AS st7_min_rate,
                   st7.max_rate AS st7_max_rate,
                   st7.stddev_rate AS st7_stddev_rate,
                   st7.cumulative_rate AS st7_cumulative_rate,
                   st7.positive_count AS st7_positive_count,
                   st7.negative_count AS st7_negative_count,
                   st7.zero_count AS st7_zero_count,
                   st7.positive_ratio AS st7_positive_ratio,
                   st7.negative_ratio AS st7_negative_ratio,
                   st7.current_positive_streak AS st7_current_positive_streak,
                   st7.longest_positive_streak AS st7_longest_positive_streak,
                   st7.current_negative_streak AS st7_current_negative_streak,
                   st7.longest_negative_streak AS st7_longest_negative_streak,
                   st7.average_positive_rate AS st7_average_positive_rate,
                   st7.average_negative_rate AS st7_average_negative_rate,
                   st7.funding_interval_hours AS st7_funding_interval_hours,
                   st7.estimated_events_per_day AS st7_estimated_events_per_day,
                   st7.estimated_daily_rate AS st7_estimated_daily_rate,
                   st7.estimated_30d_rate AS st7_estimated_30d_rate,
                   st7.negative_events_last_24h AS st7_negative_events_last_24h,
                   st7.negative_events_last_3d AS st7_negative_events_last_3d,
                   st7.stability_score AS st7_stability_score,
                   st7.trend AS st7_trend,
                   st7.reversal_warning AS st7_reversal_warning,
                   st7.data_quality AS st7_data_quality,
                   st14.id AS st14_id,
                   st14.symbol_id AS st14_symbol_id,
                   st14.window_days AS st14_window_days,
                   st14.calculated_at AS st14_calculated_at,
                   st14.event_count AS st14_event_count,
                   st14.first_event_at AS st14_first_event_at,
                   st14.last_event_at AS st14_last_event_at,
                   st14.mean_rate AS st14_mean_rate,
                   st14.median_rate AS st14_median_rate,
                   st14.min_rate AS st14_min_rate,
                   st14.max_rate AS st14_max_rate,
                   st14.stddev_rate AS st14_stddev_rate,
                   st14.cumulative_rate AS st14_cumulative_rate,
                   st14.positive_count AS st14_positive_count,
                   st14.negative_count AS st14_negative_count,
                   st14.zero_count AS st14_zero_count,
                   st14.positive_ratio AS st14_positive_ratio,
                   st14.negative_ratio AS st14_negative_ratio,
                   st14.current_positive_streak AS st14_current_positive_streak,
                   st14.longest_positive_streak AS st14_longest_positive_streak,
                   st14.current_negative_streak AS st14_current_negative_streak,
                   st14.longest_negative_streak AS st14_longest_negative_streak,
                   st14.average_positive_rate AS st14_average_positive_rate,
                   st14.average_negative_rate AS st14_average_negative_rate,
                   st14.funding_interval_hours AS st14_funding_interval_hours,
                   st14.estimated_events_per_day AS st14_estimated_events_per_day,
                   st14.estimated_daily_rate AS st14_estimated_daily_rate,
                   st14.estimated_30d_rate AS st14_estimated_30d_rate,
                   st14.negative_events_last_24h AS st14_negative_events_last_24h,
                   st14.negative_events_last_3d AS st14_negative_events_last_3d,
                   st14.stability_score AS st14_stability_score,
                   st14.trend AS st14_trend,
                   st14.reversal_warning AS st14_reversal_warning,
                   st14.data_quality AS st14_data_quality,
                   st30.id AS st30_id,
                   st30.symbol_id AS st30_symbol_id,
                   st30.window_days AS st30_window_days,
                   st30.calculated_at AS st30_calculated_at,
                   st30.event_count AS st30_event_count,
                   st30.first_event_at AS st30_first_event_at,
                   st30.last_event_at AS st30_last_event_at,
                   st30.mean_rate AS st30_mean_rate,
                   st30.median_rate AS st30_median_rate,
                   st30.min_rate AS st30_min_rate,
                   st30.max_rate AS st30_max_rate,
                   st30.stddev_rate AS st30_stddev_rate,
                   st30.cumulative_rate AS st30_cumulative_rate,
                   st30.positive_count AS st30_positive_count,
                   st30.negative_count AS st30_negative_count,
                   st30.zero_count AS st30_zero_count,
                   st30.positive_ratio AS st30_positive_ratio,
                   st30.negative_ratio AS st30_negative_ratio,
                   st30.current_positive_streak AS st30_current_positive_streak,
                   st30.longest_positive_streak AS st30_longest_positive_streak,
                   st30.current_negative_streak AS st30_current_negative_streak,
                   st30.longest_negative_streak AS st30_longest_negative_streak,
                   st30.average_positive_rate AS st30_average_positive_rate,
                   st30.average_negative_rate AS st30_average_negative_rate,
                   st30.funding_interval_hours AS st30_funding_interval_hours,
                   st30.estimated_events_per_day AS st30_estimated_events_per_day,
                   st30.estimated_daily_rate AS st30_estimated_daily_rate,
                   st30.estimated_30d_rate AS st30_estimated_30d_rate,
                   st30.negative_events_last_24h AS st30_negative_events_last_24h,
                   st30.negative_events_last_3d AS st30_negative_events_last_3d,
                   st30.stability_score AS st30_stability_score,
                   st30.trend AS st30_trend,
                   st30.reversal_warning AS st30_reversal_warning,
                   st30.data_quality AS st30_data_quality,
                   ss.history_synced_at,
                   ss.history_start_at,
                   ss.history_end_at,
                   ss.last_success_at,
                   ss.last_error_at,
                   ss.last_error,
                   ss.events_synced
            FROM symbols s
            LEFT JOIN funding_current c ON c.symbol_id = s.id
            LEFT JOIN funding_statistics st
                ON st.symbol_id = s.id AND st.window_days = $1
            LEFT JOIN funding_statistics st7
                ON st7.symbol_id = s.id AND st7.window_days = 7
            LEFT JOIN funding_statistics st14
                ON st14.symbol_id = s.id AND st14.window_days = 14
            LEFT JOIN funding_statistics st30
                ON st30.symbol_id = s.id AND st30.window_days = 30
            LEFT JOIN funding_sync_state ss ON ss.symbol_id = s.id
            WHERE s.exchange = 'BINANCE'
              AND s.strategy_eligible = TRUE
              AND s.enabled = TRUE
              AND s.futures_symbol IS NOT NULL
            ORDER BY {order_column} {order_direction}, s.base_asset ASC
            LIMIT $2
            """,
            window_days,
            limit,
        )
        return tuple(_table_row_from_row(row, settings) for row in rows)


class FundingSyncRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_enabled_eligible_symbols(
        self,
        symbols: Sequence[str] | None = None,
    ) -> tuple[FundingSymbol, ...]:
        normalized_symbols = [item.strip().upper() for item in symbols or () if item.strip()]
        rows = await self._db.fetch(
            """
            SELECT id, base_asset, futures_symbol
            FROM symbols
            WHERE exchange = 'BINANCE'
              AND strategy_eligible = TRUE
              AND enabled = TRUE
              AND futures_symbol IS NOT NULL
              AND (
                  $1::text[] IS NULL
                  OR base_asset = ANY($1::text[])
                  OR futures_symbol = ANY($1::text[])
              )
            ORDER BY base_asset
            """,
            normalized_symbols or None,
        )
        return tuple(_symbol_from_row(row) for row in rows)

    async def get_symbol(self, symbol: str) -> FundingSymbol | None:
        normalized = symbol.strip().upper()
        row = await self._db.fetchrow(
            """
            SELECT id, base_asset, futures_symbol
            FROM symbols
            WHERE exchange = 'BINANCE'
              AND strategy_eligible = TRUE
              AND enabled = TRUE
              AND futures_symbol IS NOT NULL
              AND (base_asset = $1 OR futures_symbol = $1)
            """,
            normalized,
        )
        return _symbol_from_row(row) if row is not None else None

    async def mark_history_success(
        self,
        symbol_id: int,
        *,
        history_start_at: datetime | None,
        history_end_at: datetime | None,
        events_synced: int,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO funding_sync_state (
                symbol_id,
                history_synced_at,
                history_start_at,
                history_end_at,
                last_success_at,
                last_error_at,
                last_error,
                events_synced,
                updated_at
            )
            VALUES ($1, NOW(), $2, $3, NOW(), NULL, NULL, $4, NOW())
            ON CONFLICT (symbol_id) DO UPDATE SET
                history_synced_at = EXCLUDED.history_synced_at,
                history_start_at = EXCLUDED.history_start_at,
                history_end_at = EXCLUDED.history_end_at,
                last_success_at = EXCLUDED.last_success_at,
                last_error_at = NULL,
                last_error = NULL,
                events_synced = funding_sync_state.events_synced + EXCLUDED.events_synced,
                updated_at = NOW()
            """,
            symbol_id,
            history_start_at,
            history_end_at,
            events_synced,
        )

    async def mark_error(self, symbol_id: int, error: str) -> None:
        await self._db.execute(
            """
            INSERT INTO funding_sync_state (
                symbol_id,
                last_error_at,
                last_error,
                updated_at
            )
            VALUES ($1, NOW(), $2, NOW())
            ON CONFLICT (symbol_id) DO UPDATE SET
                last_error_at = EXCLUDED.last_error_at,
                last_error = EXCLUDED.last_error,
                updated_at = NOW()
            """,
            symbol_id,
            error[:1000],
        )

    async def status_summary(self) -> FundingStatusSummary:
        row = await self._db.fetchrow(
            """
            SELECT COUNT(s.id)::int AS tracked,
                   COUNT(ss.symbol_id) FILTER (WHERE ss.history_synced_at IS NOT NULL)::int
                       AS history_synced,
                   COUNT(ss.symbol_id) FILTER (
                       WHERE ss.last_error_at IS NOT NULL
                         AND (
                             ss.last_success_at IS NULL
                             OR ss.last_error_at > ss.last_success_at
                         )
                   )::int AS failed,
                   COUNT(c.symbol_id) FILTER (WHERE c.last_funding_rate > 0)::int
                       AS current_positive,
                   COUNT(c.symbol_id) FILTER (WHERE c.last_funding_rate < 0)::int
                       AS current_negative,
                   COUNT(st.symbol_id) FILTER (WHERE st.data_quality = 'STALE')::int AS stale,
                   GREATEST(MAX(ss.last_success_at), MAX(c.updated_at), MAX(st.calculated_at))
                       AS last_sync
            FROM symbols s
            LEFT JOIN funding_sync_state ss ON ss.symbol_id = s.id
            LEFT JOIN funding_current c ON c.symbol_id = s.id
            LEFT JOIN funding_statistics st ON st.symbol_id = s.id AND st.window_days = 14
            WHERE s.exchange = 'BINANCE'
              AND s.strategy_eligible = TRUE
              AND s.enabled = TRUE
              AND s.futures_symbol IS NOT NULL
            """
        )
        if row is None:
            return FundingStatusSummary(0, 0, 0, 0, 0, 0, None)
        return FundingStatusSummary(
            tracked=_int(row["tracked"] or 0),
            history_synced=_int(row["history_synced"] or 0),
            failed=_int(row["failed"] or 0),
            current_positive=_int(row["current_positive"] or 0),
            current_negative=_int(row["current_negative"] or 0),
            stale=_int(row["stale"] or 0),
            last_sync=_datetime_or_none(row["last_sync"]),
        )


def _symbol_from_row(row: Mapping[str, object]) -> FundingSymbol:
    return FundingSymbol(
        symbol_id=_int(row["id"]),
        base_asset=str(row["base_asset"]),
        futures_symbol=str(row["futures_symbol"]),
    )


def _event_from_row(row: Mapping[str, object]) -> FundingEvent:
    return FundingEvent(
        symbol_id=_int(row["symbol_id"]),
        futures_symbol=str(row["futures_symbol"]),
        funding_time=_datetime(row["funding_time"]),
        funding_rate=_decimal(row["funding_rate"]),
        mark_price=_decimal_or_none(row["mark_price"]),
        source=str(row["source"]),
    )


def _current_from_row(row: Mapping[str, object]) -> FundingCurrent:
    return FundingCurrent(
        symbol_id=_int(row["symbol_id"]),
        futures_symbol=str(row["futures_symbol"]),
        mark_price=_decimal_or_none(row["mark_price"]),
        index_price=_decimal_or_none(row["index_price"]),
        last_funding_rate=_decimal_or_none(row["last_funding_rate"]),
        next_funding_time=_datetime_or_none(row["next_funding_time"]),
        interest_rate=_decimal_or_none(row["interest_rate"]),
        funding_interval_hours=_decimal_or_none(row["funding_interval_hours"]),
        updated_at=_datetime_or_none(row["updated_at"]),
    )


def _sync_state_from_row(row: Mapping[str, object]) -> FundingSyncState | None:
    if row.get("history_synced_at") is None and row.get("last_error_at") is None:
        return None
    return FundingSyncState(
        symbol_id=_int(row["symbol_id"]),
        history_synced_at=_datetime_or_none(row["history_synced_at"]),
        history_start_at=_datetime_or_none(row["history_start_at"]),
        history_end_at=_datetime_or_none(row["history_end_at"]),
        last_success_at=_datetime_or_none(row["last_success_at"]),
        last_error_at=_datetime_or_none(row["last_error_at"]),
        last_error=_str_or_none(row["last_error"]),
        events_synced=_int(row["events_synced"] or 0),
    )


def _statistics_from_row(row: Mapping[str, object], prefix: str = "") -> FundingStatistics | None:
    id_key = f"{prefix}id" if prefix else "id"
    if row.get(id_key) is None:
        return None
    key = _prefixed_key(prefix)
    return FundingStatistics(
        symbol_id=_int(row[key("symbol_id")]),
        window_days=_int(row[key("window_days")]),
        calculated_at=_datetime(row[key("calculated_at")]),
        event_count=_int(row[key("event_count")] or 0),
        first_event_at=_datetime_or_none(row[key("first_event_at")]),
        last_event_at=_datetime_or_none(row[key("last_event_at")]),
        mean_rate=_decimal(row[key("mean_rate")] or 0),
        median_rate=_decimal(row[key("median_rate")] or 0),
        min_rate=_decimal(row[key("min_rate")] or 0),
        max_rate=_decimal(row[key("max_rate")] or 0),
        stddev_rate=_decimal(row[key("stddev_rate")] or 0),
        cumulative_rate=_decimal(row[key("cumulative_rate")] or 0),
        positive_count=_int(row[key("positive_count")] or 0),
        negative_count=_int(row[key("negative_count")] or 0),
        zero_count=_int(row[key("zero_count")] or 0),
        positive_ratio=_decimal(row[key("positive_ratio")] or 0),
        negative_ratio=_decimal(row[key("negative_ratio")] or 0),
        current_positive_streak=_int(row[key("current_positive_streak")] or 0),
        longest_positive_streak=_int(row[key("longest_positive_streak")] or 0),
        current_negative_streak=_int(row[key("current_negative_streak")] or 0),
        longest_negative_streak=_int(row[key("longest_negative_streak")] or 0),
        average_positive_rate=_decimal(row[key("average_positive_rate")] or 0),
        average_negative_rate=_decimal(row[key("average_negative_rate")] or 0),
        funding_interval_hours=_decimal_or_none(row[key("funding_interval_hours")]),
        estimated_events_per_day=_decimal(row[key("estimated_events_per_day")] or 0),
        estimated_daily_rate=_decimal(row[key("estimated_daily_rate")] or 0),
        estimated_30d_rate=_decimal(row[key("estimated_30d_rate")] or 0),
        negative_events_last_24h=_int(row[key("negative_events_last_24h")] or 0),
        negative_events_last_3d=_int(row[key("negative_events_last_3d")] or 0),
        stability_score=_decimal(row[key("stability_score")] or 0),
        trend=FundingTrend(str(row[key("trend")] or FundingTrend.UNKNOWN.value)),
        reversal_warning=bool(row[key("reversal_warning")]),
        data_quality=DataQuality(str(row[key("data_quality")] or DataQuality.INSUFFICIENT.value)),
    )


def _prefixed_key(prefix: str):
    return lambda name: f"{prefix}{name}" if prefix else name


def _statistics_args(item: FundingStatistics) -> tuple[object, ...]:
    return (
        item.symbol_id,
        item.window_days,
        item.calculated_at,
        item.event_count,
        item.first_event_at,
        item.last_event_at,
        item.mean_rate,
        item.median_rate,
        item.min_rate,
        item.max_rate,
        item.stddev_rate,
        item.cumulative_rate,
        item.positive_count,
        item.negative_count,
        item.zero_count,
        item.positive_ratio,
        item.negative_ratio,
        item.current_positive_streak,
        item.longest_positive_streak,
        item.current_negative_streak,
        item.longest_negative_streak,
        item.average_positive_rate,
        item.average_negative_rate,
        item.funding_interval_hours,
        item.estimated_events_per_day,
        item.estimated_daily_rate,
        item.estimated_30d_rate,
        item.negative_events_last_24h,
        item.negative_events_last_3d,
        item.stability_score,
        item.trend.value,
        item.reversal_warning,
        item.data_quality.value,
    )


def _table_row_from_row(row: Mapping[str, object], settings: TradingSettings) -> FundingTableRow:
    current = None
    if row.get("current_symbol_id") is not None:
        current = FundingCurrent(
            symbol_id=_int(row["current_symbol_id"]),
            futures_symbol=str(row["current_futures_symbol"]),
            mark_price=_decimal_or_none(row["mark_price"]),
            index_price=_decimal_or_none(row["index_price"]),
            last_funding_rate=_decimal_or_none(row["last_funding_rate"]),
            next_funding_time=_datetime_or_none(row["next_funding_time"]),
            interest_rate=_decimal_or_none(row["interest_rate"]),
            funding_interval_hours=_decimal_or_none(row["current_interval_hours"]),
            updated_at=_datetime_or_none(row["current_updated_at"]),
        )
    stats_7d = _statistics_from_row(row, "st7_")
    stats_14d = _statistics_from_row(row, "st14_")
    stats_30d = _statistics_from_row(row, "st30_")
    primary = _statistics_from_row(row)
    gross_estimate = ZERO
    if stats_30d is not None:
        gross_estimate = planning_funding_income_30d(
            max_hedged_notional=settings.max_hedged_notional,
            estimated_30d_rate=stats_30d.estimated_30d_rate,
        )
    return FundingTableRow(
        symbol_id=_int(row["symbol_id"]),
        base_asset=str(row["base_asset"]),
        futures_symbol=str(row["futures_symbol"]),
        current=current,
        primary_statistics=primary,
        statistics_7d=stats_7d,
        statistics_14d=stats_14d,
        statistics_30d=stats_30d,
        sync_state=_sync_state_from_row(row),
        gross_funding_estimate_30d=gross_estimate,
    )


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    raise TypeError("expected datetime")


def _datetime_or_none(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value)


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _int(value: object) -> int:
    return int(str(value))


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def statistics_for_window(
    rows: Sequence[FundingStatistics],
    window_days: int,
) -> FundingStatistics | None:
    for row in rows:
        if row.window_days == window_days:
            return row
    return None


def with_primary_statistics(
    row: FundingTableRow,
    statistics: FundingStatistics | None,
) -> FundingTableRow:
    return replace(row, primary_statistics=statistics)
