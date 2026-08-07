from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from funding_terminal.config import Settings
from funding_terminal.domain.enums import ExecutionMode, MappingStatus
from funding_terminal.web.routes import router


class FakeDb:
    async def health_check(self) -> bool:
        return True

    async def fetchrow(self, query: str, *args: object):
        if "FROM trading_settings" in query:
            return {
                "total_capital": Decimal("4000"),
                "spot_budget": Decimal("2000"),
                "futures_margin_budget": Decimal("2000"),
                "futures_leverage": 1,
                "quote_asset": "USDT",
                "spot_maker_base_fee": Decimal("0.001"),
                "spot_taker_base_fee": Decimal("0.001"),
                "futures_maker_base_fee": Decimal("0.0002"),
                "futures_taker_base_fee": Decimal("0.0005"),
                "fee_discount_rate": Decimal("0.45"),
                "default_execution_mode": ExecutionMode.MAKER.value,
            }
        if "AS tracked" in query:
            return {
                "tracked": 1,
                "history_synced": 1,
                "failed": 0,
                "current_positive": 1,
                "current_negative": 0,
                "stale": 0,
                "last_sync": datetime.now(UTC),
            }
        if "COUNT(*) FILTER" in query:
            return {
                "total_symbols": 1,
                "eligible_symbols": 1,
                "enabled_symbols": 1,
                "rejected_symbols": 0,
            }
        if "FROM symbols" in query and "futures_symbol" in query:
            return {
                "id": 1,
                "base_asset": "BTC",
                "futures_symbol": "BTCUSDT",
            }
        if "FROM funding_current" in query:
            return {
                "symbol_id": 1,
                "futures_symbol": "BTCUSDT",
                "mark_price": Decimal("65000"),
                "index_price": Decimal("64990"),
                "last_funding_rate": Decimal("0.0001"),
                "next_funding_time": datetime.now(UTC),
                "interest_rate": Decimal("0.0001"),
                "funding_interval_hours": Decimal("8"),
                "updated_at": datetime.now(UTC),
            }
        return None

    async def fetchval(self, query: str, *args: object):
        if "COUNT(*)" in query:
            return 1
        return None

    async def fetch(self, query: str, *args: object):
        if "FROM symbols" in query and "funding_statistics st" in query:
            return [
                {
                    "symbol_id": 1,
                    "base_asset": "BTC",
                    "futures_symbol": "BTCUSDT",
                    "current_symbol_id": 1,
                    "current_futures_symbol": "BTCUSDT",
                    "mark_price": Decimal("65000"),
                    "index_price": Decimal("64990"),
                    "last_funding_rate": Decimal("0.0001"),
                    "next_funding_time": datetime.now(UTC),
                    "interest_rate": Decimal("0.0001"),
                    "current_interval_hours": Decimal("8"),
                    "current_updated_at": datetime.now(UTC),
                    "id": 1,
                    "window_days": 14,
                    "calculated_at": datetime.now(UTC),
                    "event_count": 42,
                    "first_event_at": datetime.now(UTC),
                    "last_event_at": datetime.now(UTC),
                    "mean_rate": Decimal("0.0001"),
                    "median_rate": Decimal("0.0001"),
                    "min_rate": Decimal("0.0001"),
                    "max_rate": Decimal("0.0001"),
                    "stddev_rate": Decimal("0"),
                    "cumulative_rate": Decimal("0.0042"),
                    "positive_count": 42,
                    "negative_count": 0,
                    "zero_count": 0,
                    "positive_ratio": Decimal("1"),
                    "negative_ratio": Decimal("0"),
                    "current_positive_streak": 42,
                    "longest_positive_streak": 42,
                    "current_negative_streak": 0,
                    "longest_negative_streak": 0,
                    "average_positive_rate": Decimal("0.0001"),
                    "average_negative_rate": Decimal("0"),
                    "funding_interval_hours": Decimal("8"),
                    "estimated_events_per_day": Decimal("3"),
                    "estimated_daily_rate": Decimal("0.0003"),
                    "estimated_30d_rate": Decimal("0.009"),
                    "negative_events_last_24h": 0,
                    "negative_events_last_3d": 0,
                    "stability_score": Decimal("99"),
                    "trend": "STABLE",
                    "reversal_warning": False,
                    "data_quality": "GOOD",
                    "st7_id": None,
                    "st14_id": 1,
                    "st14_symbol_id": 1,
                    "st14_window_days": 14,
                    "st14_calculated_at": datetime.now(UTC),
                    "st14_event_count": 42,
                    "st14_first_event_at": datetime.now(UTC),
                    "st14_last_event_at": datetime.now(UTC),
                    "st14_mean_rate": Decimal("0.0001"),
                    "st14_median_rate": Decimal("0.0001"),
                    "st14_min_rate": Decimal("0.0001"),
                    "st14_max_rate": Decimal("0.0001"),
                    "st14_stddev_rate": Decimal("0"),
                    "st14_cumulative_rate": Decimal("0.0042"),
                    "st14_positive_count": 42,
                    "st14_negative_count": 0,
                    "st14_zero_count": 0,
                    "st14_positive_ratio": Decimal("1"),
                    "st14_negative_ratio": Decimal("0"),
                    "st14_current_positive_streak": 42,
                    "st14_longest_positive_streak": 42,
                    "st14_current_negative_streak": 0,
                    "st14_longest_negative_streak": 0,
                    "st14_average_positive_rate": Decimal("0.0001"),
                    "st14_average_negative_rate": Decimal("0"),
                    "st14_funding_interval_hours": Decimal("8"),
                    "st14_estimated_events_per_day": Decimal("3"),
                    "st14_estimated_daily_rate": Decimal("0.0003"),
                    "st14_estimated_30d_rate": Decimal("0.009"),
                    "st14_negative_events_last_24h": 0,
                    "st14_negative_events_last_3d": 0,
                    "st14_stability_score": Decimal("99"),
                    "st14_trend": "STABLE",
                    "st14_reversal_warning": False,
                    "st14_data_quality": "GOOD",
                    "st30_id": 2,
                    "st30_symbol_id": 1,
                    "st30_window_days": 30,
                    "st30_calculated_at": datetime.now(UTC),
                    "st30_event_count": 90,
                    "st30_first_event_at": datetime.now(UTC),
                    "st30_last_event_at": datetime.now(UTC),
                    "st30_mean_rate": Decimal("0.0001"),
                    "st30_median_rate": Decimal("0.0001"),
                    "st30_min_rate": Decimal("0.0001"),
                    "st30_max_rate": Decimal("0.0001"),
                    "st30_stddev_rate": Decimal("0"),
                    "st30_cumulative_rate": Decimal("0.009"),
                    "st30_positive_count": 90,
                    "st30_negative_count": 0,
                    "st30_zero_count": 0,
                    "st30_positive_ratio": Decimal("1"),
                    "st30_negative_ratio": Decimal("0"),
                    "st30_current_positive_streak": 90,
                    "st30_longest_positive_streak": 90,
                    "st30_current_negative_streak": 0,
                    "st30_longest_negative_streak": 0,
                    "st30_average_positive_rate": Decimal("0.0001"),
                    "st30_average_negative_rate": Decimal("0"),
                    "st30_funding_interval_hours": Decimal("8"),
                    "st30_estimated_events_per_day": Decimal("3"),
                    "st30_estimated_daily_rate": Decimal("0.0003"),
                    "st30_estimated_30d_rate": Decimal("0.009"),
                    "st30_negative_events_last_24h": 0,
                    "st30_negative_events_last_3d": 0,
                    "st30_stability_score": Decimal("99"),
                    "st30_trend": "STABLE",
                    "st30_reversal_warning": False,
                    "st30_data_quality": "GOOD",
                    "history_synced_at": datetime.now(UTC),
                    "history_start_at": datetime.now(UTC),
                    "history_end_at": datetime.now(UTC),
                    "last_success_at": datetime.now(UTC),
                    "last_error_at": None,
                    "last_error": None,
                    "events_synced": 90,
                }
            ]
        if "FROM funding_statistics" in query:
            return [
                {
                    "id": 1,
                    "symbol_id": 1,
                    "window_days": 14,
                    "calculated_at": datetime.now(UTC),
                    "event_count": 42,
                    "first_event_at": datetime.now(UTC),
                    "last_event_at": datetime.now(UTC),
                    "mean_rate": Decimal("0.0001"),
                    "median_rate": Decimal("0.0001"),
                    "min_rate": Decimal("0.0001"),
                    "max_rate": Decimal("0.0001"),
                    "stddev_rate": Decimal("0"),
                    "cumulative_rate": Decimal("0.0042"),
                    "positive_count": 42,
                    "negative_count": 0,
                    "zero_count": 0,
                    "positive_ratio": Decimal("1"),
                    "negative_ratio": Decimal("0"),
                    "current_positive_streak": 42,
                    "longest_positive_streak": 42,
                    "current_negative_streak": 0,
                    "longest_negative_streak": 0,
                    "average_positive_rate": Decimal("0.0001"),
                    "average_negative_rate": Decimal("0"),
                    "funding_interval_hours": Decimal("8"),
                    "estimated_events_per_day": Decimal("3"),
                    "estimated_daily_rate": Decimal("0.0003"),
                    "estimated_30d_rate": Decimal("0.009"),
                    "negative_events_last_24h": 0,
                    "negative_events_last_3d": 0,
                    "stability_score": Decimal("99"),
                    "trend": "STABLE",
                    "reversal_warning": False,
                    "data_quality": "GOOD",
                }
            ]
        if "FROM funding_events" in query:
            return [
                {
                    "symbol_id": 1,
                    "futures_symbol": "BTCUSDT",
                    "funding_time": datetime.now(UTC),
                    "funding_rate": Decimal("0.0001"),
                    "mark_price": Decimal("65000"),
                    "source": "BINANCE",
                }
            ]
        if "FROM symbols" in query:
            return [
                {
                    "id": 1,
                    "base_asset": "BTC",
                    "spot_symbol": "BTCUSDT",
                    "futures_symbol": "BTCUSDT",
                    "spot_status": "TRADING",
                    "futures_status": "TRADING",
                    "mapping_status": MappingStatus.MATCHED.value,
                    "mapping_reason": "ok",
                    "strategy_eligible": True,
                    "enabled": True,
                    "exchange": "BINANCE",
                    "last_checked_at": datetime.now(UTC),
                }
            ]
        return []

    async def execute(self, query: str, *args: object) -> str:
        return "OK"

    async def executemany(self, query: str, args):
        return None


class FakeBinance:
    async def check_spot(self) -> bool:
        return True

    async def check_futures(self) -> bool:
        return True

    async def load_exchange_metadata(self):
        from funding_terminal.domain.models import ExchangeMetadata

        return ExchangeMetadata(spot_symbols={}, futures_symbols={}, retrieved_at=datetime.now(UTC))


def _client() -> TestClient:
    app = FastAPI()
    app.mount(
        "/static",
        StaticFiles(
            directory=Path(__file__).resolve().parents[1] / "src/funding_terminal/web/static"
        ),
        name="static",
    )
    app.state.settings = Settings(database_url="postgresql://example")
    app.state.db = FakeDb()
    app.state.binance_client = FakeBinance()
    app.include_router(router)
    return TestClient(app)


def test_dashboard_200() -> None:
    response = _client().get("/")
    assert response.status_code == 200
    assert "Funding Arbitrage Terminal" in response.text


def test_symbols_200() -> None:
    response = _client().get("/symbols")
    assert response.status_code == 200
    assert "BTC" in response.text
    assert "14d Stability Score" in response.text


def test_funding_200() -> None:
    response = _client().get("/funding")
    assert response.status_code == 200
    assert "Funding" in response.text
    assert "14d Mean" in response.text
    assert "Gross Funding Estimate" in response.text


def test_funding_detail_200() -> None:
    response = _client().get("/funding/BTC")
    assert response.status_code == 200
    assert "Current/Last Funding" in response.text
    assert "Realized Binance funding payments" in response.text


def test_settings_200() -> None:
    response = _client().get("/settings")
    assert response.status_code == 200
    assert "Total Capital" in response.text
    assert "Free Reserve" in response.text
    assert "Maximum Hedged Notional" in response.text


def test_settings_saves_budgets() -> None:
    response = _client().post(
        "/settings",
        headers={"HX-Request": "true"},
        data={
            "total_capital": "4000",
            "spot_budget": "2500",
            "futures_margin_budget": "1500",
            "futures_leverage": "2",
            "quote_asset": "USDT",
            "spot_maker_base_fee": "0.1",
            "spot_taker_base_fee": "0.1",
            "futures_maker_base_fee": "0.02",
            "futures_taker_base_fee": "0.05",
            "fee_discount": "45",
        },
    )
    assert response.status_code == 200
    assert "Settings saved." in response.text
    assert "2500" in response.text
    assert "3000" in response.text


def test_invalid_allocation_shows_error() -> None:
    response = _client().post(
        "/settings",
        headers={"HX-Request": "true"},
        data={
            "total_capital": "4000",
            "spot_budget": "3000",
            "futures_margin_budget": "1500",
            "futures_leverage": "1",
            "quote_asset": "USDT",
            "spot_maker_base_fee": "0.1",
            "spot_taker_base_fee": "0.1",
            "futures_maker_base_fee": "0.02",
            "futures_taker_base_fee": "0.05",
            "fee_discount": "45",
        },
    )
    assert response.status_code == 400
    assert "cannot exceed Total Capital" in response.text


def test_discount_update_changes_effective_values() -> None:
    response = _client().post(
        "/settings",
        headers={"HX-Request": "true"},
        data={
            "total_capital": "4000",
            "spot_budget": "2000",
            "futures_margin_budget": "2000",
            "futures_leverage": "1",
            "quote_asset": "USDT",
            "spot_maker_base_fee": "0.1",
            "spot_taker_base_fee": "0.1",
            "futures_maker_base_fee": "0.02",
            "futures_taker_base_fee": "0.05",
            "fee_discount": "0",
        },
    )
    assert response.status_code == 200
    assert "Effective Spot Maker %" in response.text
    assert "0.1%" in response.text


def test_health_endpoint() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_invalid_upload_handled() -> None:
    response = _client().post(
        "/import",
        files={"file": ("bad.txt", b"Symbol\nBTC\n", "text/plain")},
    )
    assert response.status_code == 400
    assert "Only CSV and XLSX files are supported." in response.text
