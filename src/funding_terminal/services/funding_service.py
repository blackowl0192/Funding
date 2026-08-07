from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from funding_terminal.domain.errors import BinanceUnavailableError, FundingTerminalError
from funding_terminal.domain.funding import (
    WINDOW_DAYS,
    FundingCurrent,
    FundingEvent,
    FundingStatusSummary,
    FundingSymbol,
    FundingSyncError,
    FundingSyncResult,
    FundingTableRow,
    calculate_funding_statistics,
    decimal_or_none,
    format_money,
    format_rate_percent,
    format_ratio_percent,
    utc_from_millis,
)
from funding_terminal.exchange.binance.client import BinancePublicClient
from funding_terminal.repositories.funding_repository import (
    FundingCurrentRepository,
    FundingEventRepository,
    FundingStatisticsRepository,
    FundingSyncRepository,
)
from funding_terminal.repositories.settings_repository import SettingsRepository

logger = logging.getLogger(__name__)
BINANCE_FUNDING_LIMIT = 1000
MAX_HISTORY_PAGES = 20
INCREMENTAL_OVERLAP_HOURS = 12


@dataclass(frozen=True, slots=True)
class FundingHistorySyncOutcome:
    symbol: FundingSymbol
    pages_requested: int
    events_received: int
    events_inserted: int
    events_existing: int
    statistics_updated: int


class FundingAnalyticsService:
    def __init__(
        self,
        events: FundingEventRepository,
        current: FundingCurrentRepository,
        statistics: FundingStatisticsRepository,
    ) -> None:
        self._events = events
        self._current = current
        self._statistics = statistics

    async def recalculate_symbol(
        self,
        symbol: FundingSymbol,
        *,
        now: datetime | None = None,
    ) -> int:
        calculated_at = _utc_now(now)
        start_at = calculated_at - timedelta(days=max(WINDOW_DAYS))
        events = await self._events.list_events(
            symbol.symbol_id,
            start_at=start_at,
            end_at=calculated_at,
        )
        current = await self._current.get(symbol.symbol_id)
        current_interval = current.funding_interval_hours if current else None
        snapshots = tuple(
            calculate_funding_statistics(
                events,
                symbol_id=symbol.symbol_id,
                window_days=window,
                now=calculated_at,
                current_interval_hours=current_interval,
            )
            for window in WINDOW_DAYS
        )
        return await self._statistics.upsert_many(snapshots)


class FundingHistoryService:
    def __init__(
        self,
        client: BinancePublicClient,
        events: FundingEventRepository,
        sync_state: FundingSyncRepository,
        analytics: FundingAnalyticsService,
    ) -> None:
        self._client = client
        self._events = events
        self._sync_state = sync_state
        self._analytics = analytics

    async def sync_symbol(
        self,
        symbol: FundingSymbol,
        *,
        days: int = 30,
        now: datetime | None = None,
    ) -> FundingHistorySyncOutcome:
        end_at = _utc_now(now)
        start_at = await self._history_start_at(symbol, days=days, end_at=end_at)
        logger.info(
            "funding history sync started symbol=%s start=%s end=%s",
            symbol.futures_symbol,
            start_at,
            end_at,
        )
        page_events, pages_requested = await self._load_history_pages(
            symbol,
            start_at=start_at,
            end_at=end_at,
        )
        inserted, existing = await self._events.upsert_events(page_events)
        statistics_updated = await self._analytics.recalculate_symbol(symbol, now=end_at)
        await self._sync_state.mark_history_success(
            symbol.symbol_id,
            history_start_at=start_at,
            history_end_at=end_at,
            events_synced=inserted,
        )
        logger.info(
            "funding history sync completed symbol=%s pages=%s received=%s inserted=%s existing=%s",
            symbol.futures_symbol,
            pages_requested,
            len(page_events),
            inserted,
            existing,
        )
        return FundingHistorySyncOutcome(
            symbol=symbol,
            pages_requested=pages_requested,
            events_received=len(page_events),
            events_inserted=inserted,
            events_existing=existing,
            statistics_updated=statistics_updated,
        )

    async def _history_start_at(
        self,
        symbol: FundingSymbol,
        *,
        days: int,
        end_at: datetime,
    ) -> datetime:
        full_start_at = end_at - timedelta(days=days)
        latest = await self._events.latest_event(symbol.symbol_id)
        if latest is None:
            return full_start_at
        incremental_start = latest.funding_time - timedelta(hours=INCREMENTAL_OVERLAP_HOURS)
        return max(full_start_at, incremental_start)

    async def _load_history_pages(
        self,
        symbol: FundingSymbol,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[tuple[FundingEvent, ...], int]:
        all_events: list[FundingEvent] = []
        cursor_ms = _millis(start_at)
        end_ms = _millis(end_at)
        previous_last_ms: int | None = None
        pages_requested = 0

        while cursor_ms <= end_ms and pages_requested < MAX_HISTORY_PAGES:
            payload = await self._client.get_funding_rate_history(
                symbol.futures_symbol,
                start_time_ms=cursor_ms,
                end_time_ms=end_ms,
                limit=BINANCE_FUNDING_LIMIT,
            )
            pages_requested += 1
            if not payload:
                break
            page_events = tuple(parse_funding_history_event(symbol, item) for item in payload)
            all_events.extend(page_events)
            latest_ms = max(_millis(event.funding_time) for event in page_events)
            if previous_last_ms is not None and latest_ms <= previous_last_ms:
                logger.warning(
                    "funding pagination stopped: non-advancing timestamp symbol=%s",
                    symbol.futures_symbol,
                )
                break
            previous_last_ms = latest_ms
            next_cursor_ms = latest_ms + 1
            if next_cursor_ms <= cursor_ms:
                logger.warning(
                    "funding pagination stopped: cursor did not advance symbol=%s",
                    symbol.futures_symbol,
                )
                break
            cursor_ms = next_cursor_ms
            if len(payload) < BINANCE_FUNDING_LIMIT:
                break

        return tuple(all_events), pages_requested


class FundingCurrentService:
    def __init__(
        self,
        client: BinancePublicClient,
        current: FundingCurrentRepository,
    ) -> None:
        self._client = client
        self._current = current

    async def sync_current(self, symbols: Sequence[FundingSymbol]) -> int:
        if not symbols:
            return 0
        logger.info("funding current sync started symbols=%s", len(symbols))
        premium_payload = await self._client.get_premium_index()
        funding_info_payload = await self._safe_funding_info()
        premium_by_symbol = {
            str(item.get("symbol", "")).upper(): item
            for item in premium_payload
            if isinstance(item, Mapping)
        }
        interval_by_symbol = _funding_interval_map(funding_info_payload)
        current_items: list[FundingCurrent] = []
        for symbol in symbols:
            premium = premium_by_symbol.get(symbol.futures_symbol)
            if premium is None:
                logger.warning(
                    "funding current missing premiumIndex symbol=%s",
                    symbol.futures_symbol,
                )
                continue
            current = parse_funding_current(
                symbol,
                premium,
                funding_interval_hours=interval_by_symbol.get(symbol.futures_symbol),
            )
            current_items.append(current)
        updated = await self._current.upsert_many(tuple(current_items))
        logger.info("funding current sync completed updated=%s", updated)
        return updated

    async def _safe_funding_info(self) -> Sequence[Mapping[str, object]]:
        try:
            return await self._client.get_funding_info()
        except BinanceUnavailableError as exc:
            logger.warning(
                "fundingInfo unavailable, interval will be inferred from history: %s",
                exc,
            )
            return ()


class FundingSyncService:
    def __init__(
        self,
        sync_repo: FundingSyncRepository,
        history_service: FundingHistoryService,
        current_service: FundingCurrentService,
    ) -> None:
        self._sync_repo = sync_repo
        self._history_service = history_service
        self._current_service = current_service

    async def sync_funding_universe(
        self,
        *,
        days: int = 30,
        symbols: Sequence[str] | None = None,
        current_only: bool = False,
        history_only: bool = False,
    ) -> FundingSyncResult:
        tracked_symbols = await self._sync_repo.list_enabled_eligible_symbols(symbols)
        current_updated = 0
        errors: list[FundingSyncError] = []
        success = 0
        failed = 0
        events_inserted = 0
        events_existing = 0
        statistics_updated = 0

        if tracked_symbols and not history_only:
            try:
                current_updated = await self._current_service.sync_current(tracked_symbols)
            except FundingTerminalError as exc:
                failed += len(tracked_symbols) if current_only else 0
                errors.append(FundingSyncError("CURRENT", str(exc)))
                logger.warning("funding current sync failed: %s", exc)
            else:
                if current_only:
                    success = len(tracked_symbols)

        if not current_only:
            for symbol in tracked_symbols:
                try:
                    outcome = await self._history_service.sync_symbol(symbol, days=days)
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    errors.append(FundingSyncError(symbol.base_asset, str(exc)))
                    await self._sync_repo.mark_error(symbol.symbol_id, str(exc))
                    logger.warning(
                        "funding history sync failed symbol=%s error=%s",
                        symbol.futures_symbol,
                        exc,
                    )
                    continue
                success += 1
                events_inserted += outcome.events_inserted
                events_existing += outcome.events_existing
                statistics_updated += outcome.statistics_updated

        return FundingSyncResult(
            total=len(tracked_symbols),
            success=success,
            failed=failed,
            events_inserted=events_inserted,
            events_existing=events_existing,
            statistics_updated=statistics_updated,
            current_updated=current_updated,
            errors=tuple(errors),
        )


class FundingReportService:
    def __init__(
        self,
        settings_repo: SettingsRepository,
        statistics_repo: FundingStatisticsRepository,
        sync_repo: FundingSyncRepository,
    ) -> None:
        self._settings_repo = settings_repo
        self._statistics_repo = statistics_repo
        self._sync_repo = sync_repo

    async def status_summary(self) -> FundingStatusSummary:
        return await self._sync_repo.status_summary()

    async def table_rows(
        self,
        *,
        window_days: int = 14,
        sort: str = "stability",
        direction: str = "desc",
        limit: int = 200,
    ) -> tuple[FundingTableRow, ...]:
        settings = await self._settings_repo.get()
        return await self._statistics_repo.list_table_rows(
            settings,
            window_days=window_days,
            sort=sort,
            direction=direction,
            limit=limit,
        )


def parse_funding_history_event(
    symbol: FundingSymbol,
    payload: Mapping[str, object],
) -> FundingEvent:
    payload_symbol = str(payload.get("symbol", "")).upper()
    if payload_symbol != symbol.futures_symbol:
        raise BinanceUnavailableError(
            f"Funding history returned {payload_symbol or 'unknown'} for {symbol.futures_symbol}."
        )
    funding_rate = decimal_or_none(payload.get("fundingRate"))
    funding_time = payload.get("fundingTime")
    if funding_rate is None or funding_time is None:
        raise BinanceUnavailableError(
            f"Funding history payload malformed for {symbol.futures_symbol}."
        )
    return FundingEvent(
        symbol_id=symbol.symbol_id,
        futures_symbol=symbol.futures_symbol,
        funding_time=utc_from_millis(_timestamp_value(funding_time, symbol.futures_symbol)),
        funding_rate=funding_rate,
        mark_price=decimal_or_none(payload.get("markPrice")),
    )


def parse_funding_current(
    symbol: FundingSymbol,
    payload: Mapping[str, object],
    *,
    funding_interval_hours: Decimal | None,
) -> FundingCurrent:
    payload_symbol = str(payload.get("symbol", "")).upper()
    if payload_symbol != symbol.futures_symbol:
        raise BinanceUnavailableError(
            f"Premium index returned {payload_symbol or 'unknown'} for {symbol.futures_symbol}."
        )
    next_funding_time = payload.get("nextFundingTime")
    return FundingCurrent(
        symbol_id=symbol.symbol_id,
        futures_symbol=symbol.futures_symbol,
        mark_price=decimal_or_none(payload.get("markPrice")),
        index_price=decimal_or_none(payload.get("indexPrice")),
        last_funding_rate=decimal_or_none(payload.get("lastFundingRate")),
        next_funding_time=(
            utc_from_millis(_timestamp_value(next_funding_time, symbol.futures_symbol))
            if next_funding_time
            else None
        ),
        interest_rate=decimal_or_none(payload.get("interestRate")),
        funding_interval_hours=funding_interval_hours,
    )


def format_funding_report_lines(
    rows: Sequence[FundingTableRow],
    *,
    quote_asset: str = "USDT",
) -> list[str]:
    lines = [
        "SYMBOL     MEAN       MEDIAN     POSITIVE  STREAK  "
        "STABILITY  30D_EST    GROSS_EST       QUALITY"
    ]
    for row in rows:
        stats = row.primary_statistics
        stats_30d = row.statistics_30d
        if stats is None:
            lines.append(
                f"{row.base_asset:<10} {'-':<10} {'-':<10} {'-':<9} "
                f"{'-':<7} {'-':<10} {'-':<10} {'-':<15} -"
            )
            continue
        estimate_30d = stats_30d.estimated_30d_rate if stats_30d else stats.estimated_30d_rate
        lines.append(
            f"{row.base_asset:<10} "
            f"{format_rate_percent(stats.mean_rate):<10} "
            f"{format_rate_percent(stats.median_rate):<10} "
            f"{format_ratio_percent(stats.positive_ratio):<9} "
            f"{stats.current_positive_streak:<7} "
            f"{stats.stability_score:<10} "
            f"{format_rate_percent(estimate_30d):<10} "
            f"{format_money(row.gross_funding_estimate_30d, quote_asset):<15} "
            f"{stats.data_quality.value}"
        )
    return lines


def _funding_interval_map(payload: Sequence[Mapping[str, object]]) -> dict[str, Decimal]:
    intervals: dict[str, Decimal] = {}
    for item in payload:
        symbol = str(item.get("symbol", "")).upper()
        interval = decimal_or_none(item.get("fundingIntervalHours"))
        if symbol and interval is not None and interval > 0:
            intervals[symbol] = interval
    return intervals


def _timestamp_value(value: object, symbol: str) -> int | str:
    if isinstance(value, int | str):
        return value
    raise BinanceUnavailableError(f"Funding timestamp malformed for {symbol}.")


def _millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _utc_now(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
