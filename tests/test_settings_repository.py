from decimal import Decimal

import pytest

from funding_terminal.domain.enums import ExecutionMode
from funding_terminal.repositories.settings_repository import SettingsRepository
from funding_terminal.services.settings_service import DEFAULT_TRADING_SETTINGS


class FakeSettingsDb:
    def __init__(self) -> None:
        self.executed_query = ""
        self.executed_args: tuple[object, ...] = ()

    async def fetchrow(self, query: str, *args: object):
        return {
            "total_capital": Decimal("4000"),
            "spot_budget": Decimal("2400"),
            "futures_margin_budget": Decimal("1400"),
            "futures_leverage": 2,
            "quote_asset": "USDT",
            "spot_maker_base_fee": Decimal("0.001"),
            "spot_taker_base_fee": Decimal("0.001"),
            "futures_maker_base_fee": Decimal("0.0002"),
            "futures_taker_base_fee": Decimal("0.0005"),
            "fee_discount_rate": Decimal("0.45"),
            "default_execution_mode": ExecutionMode.MAKER.value,
        }

    async def execute(self, query: str, *args: object) -> str:
        self.executed_query = query
        self.executed_args = args
        return "OK"


@pytest.mark.asyncio
async def test_settings_repository_gets_new_model() -> None:
    settings = await SettingsRepository(FakeSettingsDb()).get()  # type: ignore[arg-type]

    assert settings.spot_budget == Decimal("2400")
    assert settings.futures_margin_budget == Decimal("1400")
    assert settings.futures_leverage == 2
    assert settings.max_futures_notional == Decimal("2800")
    assert settings.max_hedged_notional == Decimal("2400")


@pytest.mark.asyncio
async def test_settings_repository_updates_base_fee_source_model() -> None:
    db = FakeSettingsDb()
    await SettingsRepository(db).update(DEFAULT_TRADING_SETTINGS)  # type: ignore[arg-type]

    assert "spot_maker_base_fee" in db.executed_query
    assert "fee_discount_rate" in db.executed_query
    assert "spot_maker_fee =" not in db.executed_query
    assert DEFAULT_TRADING_SETTINGS.fee_discount_rate in db.executed_args
