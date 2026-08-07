from decimal import Decimal

import pytest

from funding_terminal.domain.errors import SettingsValidationError
from funding_terminal.services.settings_service import DEFAULT_TRADING_SETTINGS, SettingsService


def test_default_settings_use_new_capital_and_fee_model() -> None:
    settings = DEFAULT_TRADING_SETTINGS
    assert settings.total_capital == Decimal("4000")
    assert settings.spot_budget == Decimal("2000")
    assert settings.futures_margin_budget == Decimal("2000")
    assert settings.futures_leverage == 1
    assert settings.spot_maker_base_fee == Decimal("0.001")
    assert settings.futures_taker_base_fee == Decimal("0.0005")
    assert settings.fee_discount_rate == Decimal("0.45")


@pytest.mark.parametrize(
    ("total", "spot", "futures_margin", "leverage", "reserve", "capacity", "hedged"),
    [
        ("4000", "2000", "2000", "1", "0", "2000", "2000"),
        ("4000", "2500", "1500", "2", "0", "3000", "2500"),
        ("4000", "2400", "1400", "2", "200", "2800", "2400"),
    ],
)
def test_capital_derived_values(
    total: str,
    spot: str,
    futures_margin: str,
    leverage: str,
    reserve: str,
    capacity: str,
    hedged: str,
) -> None:
    settings = _build(total=total, spot=spot, futures_margin=futures_margin, leverage=leverage)
    assert settings.free_reserve == Decimal(reserve)
    assert settings.max_futures_notional == Decimal(capacity)
    assert settings.max_hedged_notional == Decimal(hedged)


def test_capital_utilization_ratio() -> None:
    settings = _build(total="4000", spot="2400", futures_margin="1400", leverage="2")
    assert settings.capital_utilization_ratio == Decimal("0.95")


@pytest.mark.parametrize(
    ("total", "spot", "futures_margin", "leverage"),
    [
        ("4000", "3000", "1500", "1"),
        ("-1", "0", "0", "1"),
        ("0", "0", "0", "1"),
        ("4000", "-1", "0", "1"),
        ("4000", "0", "-1", "1"),
        ("4000", "0", "0", "0"),
        ("4000", "0", "0", "3"),
        ("4000", "0", "0", "1.5"),
    ],
)
def test_invalid_capital_inputs(
    total: str,
    spot: str,
    futures_margin: str,
    leverage: str,
) -> None:
    with pytest.raises(SettingsValidationError):
        _build(total=total, spot=spot, futures_margin=futures_margin, leverage=leverage)


def test_effective_fees_from_base_and_discount() -> None:
    settings = _build()
    assert settings.effective_spot_maker_fee == Decimal("0.00055")
    assert settings.effective_spot_taker_fee == Decimal("0.00055")
    assert settings.effective_futures_maker_fee == Decimal("0.000110")
    assert settings.effective_futures_taker_fee == Decimal("0.000275")


def test_zero_discount_keeps_effective_equal_to_base() -> None:
    settings = _build(discount="0")
    assert settings.effective_spot_maker_fee == settings.spot_maker_base_fee
    assert settings.effective_futures_taker_fee == settings.futures_taker_base_fee


@pytest.mark.parametrize("discount", ["100", "150", "-1"])
def test_invalid_discount(discount: str) -> None:
    with pytest.raises(SettingsValidationError):
        _build(discount=discount)


@pytest.mark.parametrize("fee", ["-0.1", "100", "NaN", "Infinity"])
def test_invalid_base_fee(fee: str) -> None:
    with pytest.raises(SettingsValidationError):
        _build(spot_maker_fee=fee)


def test_rejects_non_usdt_quote() -> None:
    with pytest.raises(SettingsValidationError):
        _build(quote_asset="USDC")


def _build(
    *,
    total: str = "4000",
    spot: str = "2000",
    futures_margin: str = "2000",
    leverage: str = "1",
    quote_asset: str = "USDT",
    spot_maker_fee: str = "0.1",
    spot_taker_fee: str = "0.1",
    futures_maker_fee: str = "0.02",
    futures_taker_fee: str = "0.05",
    discount: str = "45",
):
    return SettingsService().build_settings(
        total_capital=total,
        spot_budget=spot,
        futures_margin_budget=futures_margin,
        futures_leverage=leverage,
        quote_asset=quote_asset,
        spot_maker_base_fee_percent=spot_maker_fee,
        spot_taker_base_fee_percent=spot_taker_fee,
        futures_maker_base_fee_percent=futures_maker_fee,
        futures_taker_base_fee_percent=futures_taker_fee,
        fee_discount_percent=discount,
    )
