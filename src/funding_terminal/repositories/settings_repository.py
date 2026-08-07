from __future__ import annotations

from decimal import Decimal

from funding_terminal.db.database import Database
from funding_terminal.domain.enums import ExecutionMode
from funding_terminal.domain.models import TradingSettings
from funding_terminal.services.settings_service import DEFAULT_TRADING_SETTINGS


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self) -> TradingSettings:
        row = await self._db.fetchrow(
            """
            SELECT total_capital,
                   spot_budget,
                   futures_margin_budget,
                   futures_leverage,
                   quote_asset,
                   spot_maker_base_fee,
                   spot_taker_base_fee,
                   futures_maker_base_fee,
                   futures_taker_base_fee,
                   fee_discount_rate,
                   default_execution_mode
            FROM trading_settings
            WHERE id = 1
            """
        )
        if row is None:
            return DEFAULT_TRADING_SETTINGS
        return TradingSettings(
            total_capital=Decimal(row["total_capital"]),
            spot_budget=Decimal(row["spot_budget"]),
            futures_margin_budget=Decimal(row["futures_margin_budget"]),
            futures_leverage=int(row["futures_leverage"]),
            quote_asset=str(row["quote_asset"]),
            spot_maker_base_fee=Decimal(row["spot_maker_base_fee"]),
            spot_taker_base_fee=Decimal(row["spot_taker_base_fee"]),
            futures_maker_base_fee=Decimal(row["futures_maker_base_fee"]),
            futures_taker_base_fee=Decimal(row["futures_taker_base_fee"]),
            fee_discount_rate=Decimal(row["fee_discount_rate"]),
            default_execution_mode=ExecutionMode(str(row["default_execution_mode"])),
        )

    async def update(self, settings: TradingSettings) -> None:
        await self._db.execute(
            """
            INSERT INTO trading_settings (
                id,
                total_capital,
                spot_budget,
                futures_margin_budget,
                futures_leverage,
                quote_asset,
                spot_maker_base_fee,
                spot_taker_base_fee,
                futures_maker_base_fee,
                futures_taker_base_fee,
                fee_discount_rate,
                default_execution_mode,
                updated_at
            )
            VALUES (1, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
            ON CONFLICT (id) DO UPDATE SET
                total_capital = EXCLUDED.total_capital,
                spot_budget = EXCLUDED.spot_budget,
                futures_margin_budget = EXCLUDED.futures_margin_budget,
                futures_leverage = EXCLUDED.futures_leverage,
                quote_asset = EXCLUDED.quote_asset,
                spot_maker_base_fee = EXCLUDED.spot_maker_base_fee,
                spot_taker_base_fee = EXCLUDED.spot_taker_base_fee,
                futures_maker_base_fee = EXCLUDED.futures_maker_base_fee,
                futures_taker_base_fee = EXCLUDED.futures_taker_base_fee,
                fee_discount_rate = EXCLUDED.fee_discount_rate,
                default_execution_mode = EXCLUDED.default_execution_mode,
                updated_at = NOW()
            """,
            settings.total_capital,
            settings.spot_budget,
            settings.futures_margin_budget,
            settings.futures_leverage,
            settings.quote_asset,
            settings.spot_maker_base_fee,
            settings.spot_taker_base_fee,
            settings.futures_maker_base_fee,
            settings.futures_taker_base_fee,
            settings.fee_discount_rate,
            settings.default_execution_mode.value,
        )
