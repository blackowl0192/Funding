from datetime import UTC, datetime

from funding_terminal.domain.enums import MappingStatus
from funding_terminal.domain.models import (
    AssetInput,
    ExchangeMetadata,
    FuturesInstrument,
    SpotInstrument,
)
from funding_terminal.services.universe_service import UniverseMatcher


def test_both_matched() -> None:
    entry = UniverseMatcher().match_asset(_asset("BTC"), _metadata())
    assert entry.strategy_eligible is True
    assert entry.mapping_status == MappingStatus.MATCHED


def test_spot_missing() -> None:
    entry = UniverseMatcher().match_asset(_asset("ETH"), _metadata(spot=False))
    assert entry.strategy_eligible is False
    assert entry.mapping_status == MappingStatus.SPOT_MISSING


def test_futures_missing() -> None:
    entry = UniverseMatcher().match_asset(_asset("ETH"), _metadata(futures=False))
    assert entry.strategy_eligible is False
    assert entry.mapping_status == MappingStatus.FUTURES_MISSING


def test_inactive_spot() -> None:
    entry = UniverseMatcher().match_asset(_asset("ETH"), _metadata(spot_status="HALT"))
    assert entry.mapping_status == MappingStatus.SPOT_INACTIVE


def test_metadata_mismatch() -> None:
    entry = UniverseMatcher().match_asset(_asset("ETH"), _metadata(spot_base="ETC"))
    assert entry.mapping_status == MappingStatus.METADATA_MISMATCH


def _asset(base_asset: str) -> AssetInput:
    return AssetInput(raw_symbol=base_asset, base_asset=base_asset)


def _metadata(
    *,
    spot: bool = True,
    futures: bool = True,
    spot_status: str = "TRADING",
    spot_base: str = "ETH",
) -> ExchangeMetadata:
    spot_symbols = {}
    futures_symbols = {}
    if spot:
        spot_symbols["ETHUSDT"] = SpotInstrument(
            symbol="ETHUSDT",
            base_asset=spot_base,
            quote_asset="USDT",
            status=spot_status,
            spot_trading_allowed=True,
        )
        spot_symbols["BTCUSDT"] = SpotInstrument(
            symbol="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            status="TRADING",
            spot_trading_allowed=True,
        )
    if futures:
        futures_symbols["ETHUSDT"] = FuturesInstrument(
            symbol="ETHUSDT",
            pair="ETHUSDT",
            base_asset="ETH",
            quote_asset="USDT",
            margin_asset="USDT",
            contract_type="PERPETUAL",
            status="TRADING",
        )
        futures_symbols["BTCUSDT"] = FuturesInstrument(
            symbol="BTCUSDT",
            pair="BTCUSDT",
            base_asset="BTC",
            quote_asset="USDT",
            margin_asset="USDT",
            contract_type="PERPETUAL",
            status="TRADING",
        )
    return ExchangeMetadata(
        spot_symbols=spot_symbols,
        futures_symbols=futures_symbols,
        retrieved_at=datetime.now(UTC),
    )

