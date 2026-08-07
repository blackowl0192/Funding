import argparse
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from funding_terminal.__main__ import _parse_symbol_list, _sync_funding, format_status_lines
from funding_terminal.domain.funding import (
    DataQuality,
    FundingStatistics,
    FundingTableRow,
    FundingTrend,
)
from funding_terminal.domain.models import DashboardStats
from funding_terminal.services.funding_service import format_funding_report_lines
from funding_terminal.services.settings_service import DEFAULT_TRADING_SETTINGS


def test_status_prints_capital_and_fee_breakdown() -> None:
    settings = DEFAULT_TRADING_SETTINGS
    stats = DashboardStats(
        total_symbols=3,
        eligible_symbols=2,
        enabled_symbols=2,
        rejected_symbols=1,
        last_import_at=None,
        settings=settings,
    )

    output = "\n".join(format_status_lines(stats, settings, True, True, True))

    assert "capital:" in output
    assert "  total: 4000 USDT" in output
    assert "  spot_budget: 2000 USDT" in output
    assert "  futures_margin_budget: 2000 USDT" in output
    assert "  futures_capacity: 2000 USDT" in output
    assert "  max_hedged_notional: 2000 USDT" in output
    assert "fees:" in output
    assert "  discount: 45%" in output
    assert "  spot_maker_base: 0.1%" in output
    assert "  spot_maker_effective: 0.055%" in output
    assert "  futures_taker_base: 0.05%" in output
    assert "  futures_taker_effective: 0.0275%" in output


def test_parse_symbol_list() -> None:
    assert _parse_symbol_list("btc, ETH,,ada") == ("BTC", "ETH", "ADA")


def test_funding_report_lines_use_stage_2_terminology() -> None:
    stats = FundingStatistics(
        symbol_id=1,
        window_days=14,
        calculated_at=datetime(2026, 8, 7, tzinfo=UTC),
        event_count=42,
        first_event_at=None,
        last_event_at=None,
        mean_rate=Decimal("0.0001"),
        median_rate=Decimal("0.0001"),
        min_rate=Decimal("0.0001"),
        max_rate=Decimal("0.0001"),
        stddev_rate=Decimal("0"),
        cumulative_rate=Decimal("0.0042"),
        positive_count=42,
        negative_count=0,
        zero_count=0,
        positive_ratio=Decimal("1"),
        negative_ratio=Decimal("0"),
        current_positive_streak=42,
        longest_positive_streak=42,
        current_negative_streak=0,
        longest_negative_streak=0,
        average_positive_rate=Decimal("0.0001"),
        average_negative_rate=Decimal("0"),
        funding_interval_hours=Decimal("8"),
        estimated_events_per_day=Decimal("3"),
        estimated_daily_rate=Decimal("0.0003"),
        estimated_30d_rate=Decimal("0.009"),
        negative_events_last_24h=0,
        negative_events_last_3d=0,
        stability_score=Decimal("99"),
        trend=FundingTrend.STABLE,
        reversal_warning=False,
        data_quality=DataQuality.GOOD,
    )
    row = FundingTableRow(
        symbol_id=1,
        base_asset="BTC",
        futures_symbol="BTCUSDT",
        current=None,
        primary_statistics=stats,
        statistics_7d=None,
        statistics_14d=stats,
        statistics_30d=stats,
        sync_state=None,
        gross_funding_estimate_30d=Decimal("21.60"),
    )

    output = "\n".join(format_funding_report_lines([row]))

    assert "SYMBOL" in output
    assert "0.0100%" in output
    assert "21.60 USDT" in output
    assert "Profit" not in output


@pytest.mark.asyncio
async def test_sync_funding_rejects_mutually_exclusive_modes() -> None:
    args = argparse.Namespace(
        current_only=True,
        history_only=True,
        days=30,
        symbols="BTC",
    )

    assert await _sync_funding(None, None, args) == 2  # type: ignore[arg-type]
