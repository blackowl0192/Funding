from __future__ import annotations

from decimal import Decimal, InvalidOperation

from funding_terminal.domain.enums import ExecutionMode
from funding_terminal.domain.errors import SettingsValidationError
from funding_terminal.domain.models import TradingSettings

DEFAULT_TRADING_SETTINGS = TradingSettings(
    total_capital=Decimal("4000"),
    spot_budget=Decimal("2000"),
    futures_margin_budget=Decimal("2000"),
    futures_leverage=1,
    quote_asset="USDT",
    spot_maker_base_fee=Decimal("0.001"),
    spot_taker_base_fee=Decimal("0.001"),
    futures_maker_base_fee=Decimal("0.0002"),
    futures_taker_base_fee=Decimal("0.0005"),
    fee_discount_rate=Decimal("0.45"),
    default_execution_mode=ExecutionMode.MAKER,
)


class SettingsService:
    def build_settings(
        self,
        *,
        total_capital: str,
        spot_budget: str,
        futures_margin_budget: str,
        futures_leverage: str,
        quote_asset: str,
        spot_maker_base_fee_percent: str,
        spot_taker_base_fee_percent: str,
        futures_maker_base_fee_percent: str,
        futures_taker_base_fee_percent: str,
        fee_discount_percent: str,
        default_execution_mode: str = ExecutionMode.MAKER.value,
    ) -> TradingSettings:
        mode = self._execution_mode(default_execution_mode)
        settings = TradingSettings(
            total_capital=self._positive_decimal(total_capital, "Total capital"),
            spot_budget=self._non_negative_decimal(spot_budget, "Spot budget"),
            futures_margin_budget=self._non_negative_decimal(
                futures_margin_budget,
                "Futures Margin Budget",
            ),
            futures_leverage=self._leverage(futures_leverage),
            quote_asset=quote_asset.strip().upper(),
            spot_maker_base_fee=self.percent_to_fraction(
                spot_maker_base_fee_percent,
                "Spot maker base fee",
            ),
            spot_taker_base_fee=self.percent_to_fraction(
                spot_taker_base_fee_percent,
                "Spot taker base fee",
            ),
            futures_maker_base_fee=self.percent_to_fraction(
                futures_maker_base_fee_percent,
                "Futures maker base fee",
            ),
            futures_taker_base_fee=self.percent_to_fraction(
                futures_taker_base_fee_percent,
                "Futures taker base fee",
            ),
            fee_discount_rate=self.percent_to_fraction(fee_discount_percent, "Fee discount"),
            default_execution_mode=mode,
        )
        self.validate(settings)
        return settings

    def validate(self, settings: TradingSettings) -> None:
        if settings.quote_asset != "USDT":
            raise SettingsValidationError("Quote asset must be USDT in Stage 1.")
        if settings.total_capital <= 0:
            raise SettingsValidationError("Total capital must be positive.")
        if settings.spot_budget < 0:
            raise SettingsValidationError("Spot budget cannot be negative.")
        if settings.futures_margin_budget < 0:
            raise SettingsValidationError("Futures Margin Budget cannot be negative.")
        if settings.spot_budget + settings.futures_margin_budget > settings.total_capital:
            raise SettingsValidationError(
                "Spot budget plus Futures Margin Budget cannot exceed Total Capital."
            )
        if settings.futures_leverage not in {1, 2}:
            raise SettingsValidationError("Futures leverage must be 1x or 2x in Stage 1.")
        fees = (
            settings.spot_maker_base_fee,
            settings.spot_taker_base_fee,
            settings.futures_maker_base_fee,
            settings.futures_taker_base_fee,
        )
        if any(fee < 0 for fee in fees):
            raise SettingsValidationError("Base fees cannot be negative.")
        if any(fee >= Decimal("1") for fee in fees):
            raise SettingsValidationError("Base fees must be less than 100%.")
        if settings.fee_discount_rate < 0:
            raise SettingsValidationError("Fee discount cannot be negative.")
        if settings.fee_discount_rate >= Decimal("1"):
            raise SettingsValidationError("Fee discount must be less than 100%.")

    def percent_to_fraction(self, value: str, label: str = "Fee") -> Decimal:
        percent = self._decimal(value, label)
        if percent < 0:
            raise SettingsValidationError(f"{label} cannot be negative.")
        return percent / Decimal("100")

    def fraction_to_percent(self, value: Decimal) -> Decimal:
        return value * Decimal("100")

    def _non_negative_decimal(self, value: str, label: str) -> Decimal:
        decimal_value = self._decimal(value, label)
        if decimal_value < 0:
            raise SettingsValidationError(f"{label} cannot be negative.")
        return decimal_value

    def _positive_decimal(self, value: str, label: str) -> Decimal:
        decimal_value = self._decimal(value, label)
        if decimal_value <= 0:
            raise SettingsValidationError(f"{label} must be positive.")
        return decimal_value

    def _decimal(self, value: str, label: str) -> Decimal:
        try:
            decimal_value = Decimal(value.strip())
        except (InvalidOperation, AttributeError) as exc:
            raise SettingsValidationError(f"{label} must be a valid decimal number.") from exc
        if not decimal_value.is_finite():
            raise SettingsValidationError(f"{label} must be a finite decimal number.")
        return decimal_value

    def _leverage(self, value: str) -> int:
        normalized = value.strip()
        if normalized not in {"1", "2"}:
            raise SettingsValidationError("Futures leverage must be 1x or 2x in Stage 1.")
        return int(normalized)

    def _execution_mode(self, value: str) -> ExecutionMode:
        try:
            return ExecutionMode(value.strip().upper())
        except ValueError as exc:
            allowed = ", ".join(mode.value for mode in ExecutionMode)
            raise SettingsValidationError(f"Execution mode must be one of: {allowed}.") from exc


def format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")
