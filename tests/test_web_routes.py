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
        if "COUNT(*) FILTER" in query:
            return {
                "total_symbols": 1,
                "eligible_symbols": 1,
                "enabled_symbols": 1,
                "rejected_symbols": 0,
            }
        return None

    async def fetchval(self, query: str, *args: object):
        if "COUNT(*)" in query:
            return 1
        return None

    async def fetch(self, query: str, *args: object):
        if "FROM symbols" in query:
            return [
                {
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
