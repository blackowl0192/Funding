from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

ZERO = Decimal("0")
ONE = Decimal("1")
HOURS_PER_DAY = Decimal("24")
WINDOW_DAYS = (7, 14, 30)


class DataQuality(StrEnum):
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    STALE = "STALE"


class FundingTrend(StrEnum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    DETERIORATING = "DETERIORATING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FundingSymbol:
    symbol_id: int
    base_asset: str
    futures_symbol: str


@dataclass(frozen=True, slots=True)
class FundingEvent:
    symbol_id: int
    futures_symbol: str
    funding_time: datetime
    funding_rate: Decimal
    mark_price: Decimal | None = None
    source: str = "BINANCE"


@dataclass(frozen=True, slots=True)
class FundingCurrent:
    symbol_id: int
    futures_symbol: str
    mark_price: Decimal | None
    index_price: Decimal | None
    last_funding_rate: Decimal | None
    next_funding_time: datetime | None
    interest_rate: Decimal | None
    funding_interval_hours: Decimal | None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FundingSyncState:
    symbol_id: int
    history_synced_at: datetime | None
    history_start_at: datetime | None
    history_end_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    events_synced: int


@dataclass(frozen=True, slots=True)
class FundingStatistics:
    symbol_id: int
    window_days: int
    calculated_at: datetime
    event_count: int
    first_event_at: datetime | None
    last_event_at: datetime | None
    mean_rate: Decimal
    median_rate: Decimal
    min_rate: Decimal
    max_rate: Decimal
    stddev_rate: Decimal
    cumulative_rate: Decimal
    positive_count: int
    negative_count: int
    zero_count: int
    positive_ratio: Decimal
    negative_ratio: Decimal
    current_positive_streak: int
    longest_positive_streak: int
    current_negative_streak: int
    longest_negative_streak: int
    average_positive_rate: Decimal
    average_negative_rate: Decimal
    funding_interval_hours: Decimal | None
    estimated_events_per_day: Decimal
    estimated_daily_rate: Decimal
    estimated_30d_rate: Decimal
    negative_events_last_24h: int
    negative_events_last_3d: int
    stability_score: Decimal
    trend: FundingTrend
    reversal_warning: bool
    data_quality: DataQuality


@dataclass(frozen=True, slots=True)
class FundingSyncError:
    symbol: str
    error: str


@dataclass(frozen=True, slots=True)
class FundingSyncResult:
    total: int
    success: int
    failed: int
    events_inserted: int
    events_existing: int
    statistics_updated: int
    current_updated: int
    errors: tuple[FundingSyncError, ...] = ()


@dataclass(frozen=True, slots=True)
class FundingStatusSummary:
    tracked: int
    history_synced: int
    failed: int
    current_positive: int
    current_negative: int
    stale: int
    last_sync: datetime | None


@dataclass(frozen=True, slots=True)
class FundingTableRow:
    symbol_id: int
    base_asset: str
    futures_symbol: str
    current: FundingCurrent | None
    primary_statistics: FundingStatistics | None
    statistics_7d: FundingStatistics | None
    statistics_14d: FundingStatistics | None
    statistics_30d: FundingStatistics | None
    sync_state: FundingSyncState | None
    gross_funding_estimate_30d: Decimal


def utc_from_millis(value: int | str) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def decimal_or_none(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite():
        return None
    return decimal_value


def parse_rate_percent(value: str) -> Decimal:
    normalized = value.strip().removesuffix("%").strip()
    try:
        return Decimal(normalized) / Decimal("100")
    except InvalidOperation as exc:
        raise ValueError("Funding rate percent must be a decimal value.") from exc


def format_rate_percent(value: Decimal | None, decimals: int = 4) -> str:
    if value is None:
        return "-"
    quant = Decimal("1").scaleb(-decimals)
    return f"{(value * Decimal('100')).quantize(quant, rounding=ROUND_HALF_UP)}%"


def format_ratio_percent(value: Decimal | None, decimals: int = 1) -> str:
    if value is None:
        return "-"
    quant = Decimal("1").scaleb(-decimals)
    return f"{(value * Decimal('100')).quantize(quant, rounding=ROUND_HALF_UP)}%"


def format_money(value: Decimal | None, quote_asset: str = "USDT") -> str:
    if value is None:
        return "-"
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)} {quote_asset}"


def planning_funding_income_30d(
    *,
    max_hedged_notional: Decimal,
    estimated_30d_rate: Decimal,
) -> Decimal:
    return (max_hedged_notional * estimated_30d_rate).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def calculate_funding_statistics(
    events: Iterable[FundingEvent],
    *,
    symbol_id: int,
    window_days: int,
    now: datetime | None = None,
    current_interval_hours: Decimal | None = None,
) -> FundingStatistics:
    if window_days not in WINDOW_DAYS:
        raise ValueError("window_days must be one of 7, 14, 30.")
    calculated_at = ensure_utc(now or datetime.now(UTC))
    cutoff = calculated_at - timedelta(days=window_days)
    ordered = _dedupe_and_sort(
        event
        for event in events
        if cutoff <= ensure_utc(event.funding_time) <= calculated_at
    )
    if not ordered:
        return _empty_statistics(symbol_id, window_days, calculated_at)

    rates = [event.funding_rate for event in ordered]
    event_count = len(rates)
    cumulative_rate = sum(rates, ZERO)
    mean_rate = cumulative_rate / Decimal(event_count)
    median_rate = _median(rates)
    min_rate = min(rates)
    max_rate = max(rates)
    stddev_rate = _stddev(rates, mean_rate)
    positive_rates = [rate for rate in rates if rate > ZERO]
    negative_rates = [rate for rate in rates if rate < ZERO]
    zero_count = event_count - len(positive_rates) - len(negative_rates)
    positive_ratio = Decimal(len(positive_rates)) / Decimal(event_count)
    negative_ratio = Decimal(len(negative_rates)) / Decimal(event_count)

    interval_hours, interval_changed = _funding_interval_hours(ordered, current_interval_hours)
    estimated_events_per_day = _estimated_events_per_day(
        ordered,
        interval_hours,
        interval_changed=interval_changed,
    )
    estimated_daily_rate = mean_rate * estimated_events_per_day
    estimated_30d_rate = estimated_daily_rate * Decimal("30")
    current_positive_streak = _current_streak(rates, positive=True)
    current_negative_streak = _current_streak(rates, positive=False)
    longest_positive_streak = _longest_streak(rates, positive=True)
    longest_negative_streak = _longest_streak(rates, positive=False)
    negative_events_last_24h = _negative_count_since(ordered, calculated_at - timedelta(hours=24))
    negative_events_last_3d = _negative_count_since(ordered, calculated_at - timedelta(days=3))
    data_quality = _data_quality(
        ordered,
        window_days=window_days,
        now=calculated_at,
        interval_hours=interval_hours,
        estimated_events_per_day=estimated_events_per_day,
        interval_changed=interval_changed,
    )
    trend = _trend(ordered, calculated_at)
    reversal_warning = _reversal_warning(
        rates,
        mean_rate=mean_rate,
        stddev_rate=stddev_rate,
        positive_ratio=positive_ratio,
        current_negative_streak=current_negative_streak,
        negative_events_last_24h=negative_events_last_24h,
    )
    stability_score = _stability_score(
        positive_ratio=positive_ratio,
        mean_rate=mean_rate,
        median_rate=median_rate,
        stddev_rate=stddev_rate,
        current_positive_streak=current_positive_streak,
        longest_negative_streak=longest_negative_streak,
        estimated_events_per_day=estimated_events_per_day,
        data_quality=data_quality,
    )

    return FundingStatistics(
        symbol_id=symbol_id,
        window_days=window_days,
        calculated_at=calculated_at,
        event_count=event_count,
        first_event_at=ordered[0].funding_time,
        last_event_at=ordered[-1].funding_time,
        mean_rate=mean_rate,
        median_rate=median_rate,
        min_rate=min_rate,
        max_rate=max_rate,
        stddev_rate=stddev_rate,
        cumulative_rate=cumulative_rate,
        positive_count=len(positive_rates),
        negative_count=len(negative_rates),
        zero_count=zero_count,
        positive_ratio=positive_ratio,
        negative_ratio=negative_ratio,
        current_positive_streak=current_positive_streak,
        longest_positive_streak=longest_positive_streak,
        current_negative_streak=current_negative_streak,
        longest_negative_streak=longest_negative_streak,
        average_positive_rate=_average(positive_rates),
        average_negative_rate=_average(negative_rates),
        funding_interval_hours=interval_hours,
        estimated_events_per_day=estimated_events_per_day,
        estimated_daily_rate=estimated_daily_rate,
        estimated_30d_rate=estimated_30d_rate,
        negative_events_last_24h=negative_events_last_24h,
        negative_events_last_3d=negative_events_last_3d,
        stability_score=stability_score,
        trend=trend,
        reversal_warning=reversal_warning,
        data_quality=data_quality,
    )


def _empty_statistics(
    symbol_id: int,
    window_days: int,
    calculated_at: datetime,
) -> FundingStatistics:
    return FundingStatistics(
        symbol_id=symbol_id,
        window_days=window_days,
        calculated_at=calculated_at,
        event_count=0,
        first_event_at=None,
        last_event_at=None,
        mean_rate=ZERO,
        median_rate=ZERO,
        min_rate=ZERO,
        max_rate=ZERO,
        stddev_rate=ZERO,
        cumulative_rate=ZERO,
        positive_count=0,
        negative_count=0,
        zero_count=0,
        positive_ratio=ZERO,
        negative_ratio=ZERO,
        current_positive_streak=0,
        longest_positive_streak=0,
        current_negative_streak=0,
        longest_negative_streak=0,
        average_positive_rate=ZERO,
        average_negative_rate=ZERO,
        funding_interval_hours=None,
        estimated_events_per_day=ZERO,
        estimated_daily_rate=ZERO,
        estimated_30d_rate=ZERO,
        negative_events_last_24h=0,
        negative_events_last_3d=0,
        stability_score=ZERO,
        trend=FundingTrend.UNKNOWN,
        reversal_warning=False,
        data_quality=DataQuality.INSUFFICIENT,
    )


def _dedupe_and_sort(events: Iterable[FundingEvent]) -> list[FundingEvent]:
    deduped: dict[datetime, FundingEvent] = {}
    for event in events:
        deduped[ensure_utc(event.funding_time)] = FundingEvent(
            symbol_id=event.symbol_id,
            futures_symbol=event.futures_symbol,
            funding_time=ensure_utc(event.funding_time),
            funding_rate=event.funding_rate,
            mark_price=event.mark_price,
            source=event.source,
        )
    return sorted(deduped.values(), key=lambda item: item.funding_time)


def _average(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    return sum(values, ZERO) / Decimal(len(values))


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _stddev(values: Sequence[Decimal], mean: Decimal) -> Decimal:
    if not values:
        return ZERO
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    return variance.sqrt()


def _current_streak(values: Sequence[Decimal], *, positive: bool) -> int:
    count = 0
    for value in reversed(values):
        if (positive and value > ZERO) or (not positive and value < ZERO):
            count += 1
            continue
        break
    return count


def _longest_streak(values: Sequence[Decimal], *, positive: bool) -> int:
    longest = 0
    current = 0
    for value in values:
        if (positive and value > ZERO) or (not positive and value < ZERO):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _funding_interval_hours(
    events: Sequence[FundingEvent],
    current_interval_hours: Decimal | None,
) -> tuple[Decimal | None, bool]:
    if current_interval_hours is not None and current_interval_hours > ZERO:
        detected_interval, changed = _detected_interval_hours(events)
        return current_interval_hours, changed if detected_interval is not None else False
    return _detected_interval_hours(events)


def _detected_interval_hours(events: Sequence[FundingEvent]) -> tuple[Decimal | None, bool]:
    intervals = [
        Decimal(str((right.funding_time - left.funding_time).total_seconds())) / Decimal("3600")
        for left, right in zip(events, events[1:], strict=False)
        if right.funding_time > left.funding_time
    ]
    if not intervals:
        return None, False
    interval = _median(intervals)
    if interval <= ZERO:
        return None, False
    tolerance = interval * Decimal("0.20")
    changed = any(abs(item - interval) > tolerance for item in intervals)
    return interval, changed


def _estimated_events_per_day(
    events: Sequence[FundingEvent],
    interval_hours: Decimal | None,
    *,
    interval_changed: bool,
) -> Decimal:
    if interval_hours is not None and interval_hours > ZERO and not interval_changed:
        return HOURS_PER_DAY / interval_hours
    if len(events) > 1:
        duration_seconds = (events[-1].funding_time - events[0].funding_time).total_seconds()
        duration_days = Decimal(str(duration_seconds))
        duration_days = duration_days / Decimal("86400")
        if duration_days > ZERO:
            return Decimal(len(events)) / duration_days
    if interval_hours is not None and interval_hours > ZERO:
        return HOURS_PER_DAY / interval_hours
    return ZERO


def _negative_count_since(events: Sequence[FundingEvent], since: datetime) -> int:
    return sum(1 for event in events if event.funding_time >= since and event.funding_rate < ZERO)


def _data_quality(
    events: Sequence[FundingEvent],
    *,
    window_days: int,
    now: datetime,
    interval_hours: Decimal | None,
    estimated_events_per_day: Decimal,
    interval_changed: bool,
) -> DataQuality:
    if len(events) < 2:
        return DataQuality.INSUFFICIENT

    latest_age_seconds = (now - events[-1].funding_time).total_seconds()
    latest_age_hours = Decimal(str(latest_age_seconds)) / Decimal("3600")
    stale_threshold = Decimal("36")
    if interval_hours is not None and interval_hours > ZERO:
        stale_threshold = max(stale_threshold, interval_hours * Decimal("3"))
    if latest_age_hours > stale_threshold:
        return DataQuality.STALE

    observed_days = Decimal(str((events[-1].funding_time - events[0].funding_time).total_seconds()))
    observed_days = observed_days / Decimal("86400")
    if interval_hours is not None and interval_hours > ZERO:
        observed_days += interval_hours / HOURS_PER_DAY
    coverage_ratio = _clamp_decimal(observed_days / Decimal(window_days), ZERO, ONE)
    expected_count = estimated_events_per_day * Decimal(window_days)
    if expected_count > ZERO:
        count_ratio = _clamp_decimal(Decimal(len(events)) / expected_count, ZERO, ONE)
    else:
        count_ratio = ZERO
    large_gap = _has_large_gap(events)

    if coverage_ratio >= Decimal("0.75") and count_ratio >= Decimal("0.75") and not large_gap:
        return DataQuality.PARTIAL if interval_changed else DataQuality.GOOD
    if len(events) >= 3 and coverage_ratio >= Decimal("0.25"):
        return DataQuality.PARTIAL
    return DataQuality.INSUFFICIENT


def _has_large_gap(events: Sequence[FundingEvent]) -> bool:
    interval, _ = _detected_interval_hours(events)
    if interval is None:
        return False
    intervals = [
        Decimal(str((right.funding_time - left.funding_time).total_seconds())) / Decimal("3600")
        for left, right in zip(events, events[1:], strict=False)
        if right.funding_time > left.funding_time
    ]
    return any(item > interval * Decimal("2.5") for item in intervals)


def _trend(events: Sequence[FundingEvent], now: datetime) -> FundingTrend:
    last_start = now - timedelta(days=7)
    previous_start = now - timedelta(days=14)
    last_rates = [event.funding_rate for event in events if event.funding_time >= last_start]
    previous_rates = [
        event.funding_rate
        for event in events
        if previous_start <= event.funding_time < last_start
    ]
    if len(last_rates) < 2 or len(previous_rates) < 2:
        return FundingTrend.UNKNOWN
    delta = _average(last_rates) - _average(previous_rates)
    tolerance = Decimal("0.00002")
    if delta > tolerance:
        return FundingTrend.IMPROVING
    if delta < -tolerance:
        return FundingTrend.DETERIORATING
    return FundingTrend.STABLE


def _reversal_warning(
    values: Sequence[Decimal],
    *,
    mean_rate: Decimal,
    stddev_rate: Decimal,
    positive_ratio: Decimal,
    current_negative_streak: int,
    negative_events_last_24h: int,
) -> bool:
    if not values or positive_ratio < Decimal("0.60"):
        return False
    if current_negative_streak >= 2:
        return True
    deterioration_threshold = max(stddev_rate, Decimal("0.00005"))
    return negative_events_last_24h > 0 and values[-1] < mean_rate - deterioration_threshold


def _stability_score(
    *,
    positive_ratio: Decimal,
    mean_rate: Decimal,
    median_rate: Decimal,
    stddev_rate: Decimal,
    current_positive_streak: int,
    longest_negative_streak: int,
    estimated_events_per_day: Decimal,
    data_quality: DataQuality,
) -> Decimal:
    positive_component = positive_ratio * Decimal("40")
    scale = max(abs(mean_rate), abs(median_rate), Decimal("0.0001"))
    low_volatility = ONE - _clamp_decimal(stddev_rate / scale, ZERO, ONE)
    volatility_component = low_volatility * Decimal("20")
    negative_target = max(estimated_events_per_day, Decimal("1"))
    negative_component = (
        ONE - _clamp_decimal(Decimal(longest_negative_streak) / negative_target, ZERO, ONE)
    ) * Decimal("5")
    streak_target = max(estimated_events_per_day * Decimal("3"), Decimal("3"))
    streak_component = (
        _clamp_decimal(Decimal(current_positive_streak) / streak_target, ZERO, ONE)
        * Decimal("15")
    )
    if median_rate > ZERO and mean_rate > ZERO:
        median_component = Decimal("10")
    elif median_rate > ZERO:
        median_component = Decimal("6")
    else:
        median_component = ZERO
    quality_component = {
        DataQuality.GOOD: Decimal("10"),
        DataQuality.PARTIAL: Decimal("6"),
        DataQuality.STALE: Decimal("4"),
        DataQuality.INSUFFICIENT: Decimal("1"),
    }[data_quality]
    raw_score = (
        positive_component
        + volatility_component
        + negative_component
        + streak_component
        + median_component
        + quality_component
    )
    return _clamp_decimal(raw_score, ZERO, Decimal("100")).quantize(Decimal("0.01"))


def _clamp_decimal(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return max(minimum, min(maximum, value))
