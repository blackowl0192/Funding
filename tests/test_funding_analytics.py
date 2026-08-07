from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from funding_terminal.domain.enums import ExecutionMode
from funding_terminal.domain.funding import (
    DataQuality,
    FundingEvent,
    FundingTrend,
    calculate_funding_statistics,
    format_money,
    format_rate_percent,
    parse_rate_percent,
    planning_funding_income_30d,
)
from funding_terminal.domain.models import TradingSettings

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def event(offset_hours: int, rate: str, *, symbol_id: int = 1) -> FundingEvent:
    return FundingEvent(
        symbol_id=symbol_id,
        futures_symbol="BTCUSDT",
        funding_time=NOW + timedelta(hours=offset_hours),
        funding_rate=Decimal(rate),
        mark_price=Decimal("65000"),
    )


def every_8h(count: int, rate: str, *, end: datetime = NOW) -> tuple[FundingEvent, ...]:
    start = end - timedelta(hours=8 * (count - 1))
    return tuple(
        FundingEvent(
            symbol_id=1,
            futures_symbol="BTCUSDT",
            funding_time=start + timedelta(hours=8 * index),
            funding_rate=Decimal(rate),
        )
        for index in range(count)
    )


def test_funding_rate_format_and_parse_are_fraction_based() -> None:
    assert format_rate_percent(Decimal("0.0001")) == "0.0100%"
    assert parse_rate_percent("0.0100%") == Decimal("0.0001")


def test_mixed_metrics() -> None:
    stats = calculate_funding_statistics(
        [
            event(-32, "0.0001"),
            event(-24, "0.0002"),
            event(-16, "-0.0001"),
            event(-8, "0"),
            event(0, "0.0003"),
        ],
        symbol_id=1,
        window_days=7,
        now=NOW,
    )

    assert stats.event_count == 5
    assert stats.mean_rate == Decimal("0.0001")
    assert stats.median_rate == Decimal("0.0001")
    assert stats.cumulative_rate == Decimal("0.0005")
    assert stats.min_rate == Decimal("-0.0001")
    assert stats.max_rate == Decimal("0.0003")
    assert stats.positive_count == 3
    assert stats.negative_count == 1
    assert stats.zero_count == 1
    assert stats.positive_ratio == Decimal("0.6")
    assert stats.negative_ratio == Decimal("0.2")
    assert stats.current_positive_streak == 1
    assert stats.longest_positive_streak == 2
    assert stats.current_negative_streak == 0
    assert stats.longest_negative_streak == 1


def test_empty_history_is_insufficient() -> None:
    stats = calculate_funding_statistics([], symbol_id=1, window_days=30, now=NOW)

    assert stats.event_count == 0
    assert stats.data_quality == DataQuality.INSUFFICIENT
    assert stats.trend == FundingTrend.UNKNOWN


def test_single_event_is_insufficient() -> None:
    stats = calculate_funding_statistics([event(0, "0.0001")], symbol_id=1, window_days=7, now=NOW)

    assert stats.event_count == 1
    assert stats.stddev_rate == Decimal("0")
    assert stats.current_positive_streak == 1
    assert stats.data_quality == DataQuality.INSUFFICIENT


def test_all_positive_has_positive_streaks_and_high_stability() -> None:
    stats = calculate_funding_statistics(
        every_8h(43, "0.0001"),
        symbol_id=1,
        window_days=14,
        now=NOW,
    )

    assert stats.positive_count == 43
    assert stats.negative_count == 0
    assert stats.current_positive_streak == 43
    assert stats.longest_positive_streak == 43
    assert stats.funding_interval_hours == Decimal("8")
    assert stats.estimated_events_per_day == Decimal("3")
    assert stats.estimated_30d_rate == Decimal("0.0090")
    assert stats.data_quality == DataQuality.GOOD
    assert stats.stability_score > Decimal("85")


def test_all_negative_has_negative_streaks() -> None:
    stats = calculate_funding_statistics(
        every_8h(22, "-0.0001"),
        symbol_id=1,
        window_days=7,
        now=NOW,
    )

    assert stats.positive_ratio == Decimal("0")
    assert stats.negative_ratio == Decimal("1")
    assert stats.current_negative_streak == 22
    assert stats.longest_negative_streak == 22
    assert stats.stability_score < Decimal("40")


def test_zeros_are_not_positive_or_negative() -> None:
    stats = calculate_funding_statistics(every_8h(22, "0"), symbol_id=1, window_days=7, now=NOW)

    assert stats.zero_count == 22
    assert stats.positive_ratio == Decimal("0")
    assert stats.negative_ratio == Decimal("0")
    assert stats.current_positive_streak == 0
    assert stats.current_negative_streak == 0


def test_four_hour_interval_uses_six_events_per_day() -> None:
    events = tuple(event(-4 * (12 - index), "0.0001") for index in range(13))

    stats = calculate_funding_statistics(events, symbol_id=1, window_days=7, now=NOW)

    assert stats.funding_interval_hours == Decimal("4")
    assert stats.estimated_events_per_day == Decimal("6")
    assert stats.estimated_30d_rate == Decimal("0.0180")


def test_changing_interval_uses_historical_frequency() -> None:
    events = [
        event(-28, "0.0001"),
        event(-20, "0.0001"),
        event(-16, "0.0001"),
        event(-4, "0.0001"),
    ]

    stats = calculate_funding_statistics(events, symbol_id=1, window_days=7, now=NOW)

    assert stats.funding_interval_hours == Decimal("8")
    assert stats.estimated_events_per_day != Decimal("3")


def test_recent_negative_events_and_reversal_warning() -> None:
    stats = calculate_funding_statistics(
        [
            event(-48, "0.0002"),
            event(-40, "0.0002"),
            event(-32, "0.0002"),
            event(-24, "0.0002"),
            event(-16, "0.0002"),
            event(-8, "-0.0001"),
            event(0, "-0.0001"),
        ],
        symbol_id=1,
        window_days=7,
        now=NOW,
    )

    assert stats.negative_events_last_24h == 2
    assert stats.negative_events_last_3d == 2
    assert stats.current_negative_streak == 2
    assert stats.reversal_warning is True


def test_trend_compares_last_7d_to_previous_7d() -> None:
    previous = [
        FundingEvent(1, "BTCUSDT", NOW - timedelta(days=13, hours=-8 * index), Decimal("0.00005"))
        for index in range(3)
    ]
    recent = [
        FundingEvent(1, "BTCUSDT", NOW - timedelta(days=2, hours=-8 * index), Decimal("0.0002"))
        for index in range(3)
    ]

    stats = calculate_funding_statistics(previous + recent, symbol_id=1, window_days=14, now=NOW)

    assert stats.trend == FundingTrend.IMPROVING


def test_persistent_small_funding_scores_above_spiky_unstable_funding() -> None:
    spiky = [
        event(-32, "0.0020"),
        event(-24, "0.0001"),
        event(-16, "-0.0005"),
        event(-8, "0.0015"),
        event(0, "-0.0004"),
    ]
    stable = [
        event(-32, "0.00010"),
        event(-24, "0.00011"),
        event(-16, "0.00010"),
        event(-8, "0.00012"),
        event(0, "0.00010"),
    ]

    spiky_stats = calculate_funding_statistics(spiky, symbol_id=1, window_days=7, now=NOW)
    stable_stats = calculate_funding_statistics(stable, symbol_id=1, window_days=7, now=NOW)

    assert stable_stats.stability_score > spiky_stats.stability_score


def test_planning_funding_income_uses_max_hedged_notional() -> None:
    settings = TradingSettings(
        total_capital=Decimal("4000"),
        spot_budget=Decimal("2400"),
        futures_margin_budget=Decimal("1400"),
        futures_leverage=2,
        quote_asset="USDT",
        spot_maker_base_fee=Decimal("0.001"),
        spot_taker_base_fee=Decimal("0.001"),
        futures_maker_base_fee=Decimal("0.0002"),
        futures_taker_base_fee=Decimal("0.0005"),
        fee_discount_rate=Decimal("0.45"),
        default_execution_mode=ExecutionMode.MAKER,
    )

    assert settings.max_futures_notional == Decimal("2800")
    assert settings.max_hedged_notional == Decimal("2400")
    assert planning_funding_income_30d(
        max_hedged_notional=settings.max_hedged_notional,
        estimated_30d_rate=Decimal("0.009"),
    ) == Decimal("21.60")
    assert format_money(Decimal("21.60")) == "21.60 USDT"


def test_invalid_window_rejected() -> None:
    with pytest.raises(ValueError, match="window_days"):
        calculate_funding_statistics([], symbol_id=1, window_days=10, now=NOW)
