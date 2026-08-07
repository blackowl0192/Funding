from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from funding_terminal.domain.errors import BinanceUnavailableError
from funding_terminal.domain.models import ExchangeMetadata, FuturesInstrument, SpotInstrument


def parse_exchange_metadata(
    spot_payload: Mapping[str, object],
    futures_payload: Mapping[str, object],
) -> ExchangeMetadata:
    return ExchangeMetadata(
        spot_symbols=parse_spot_exchange_info(spot_payload),
        futures_symbols=parse_futures_exchange_info(futures_payload),
        retrieved_at=datetime.now(UTC),
    )


def parse_spot_exchange_info(payload: Mapping[str, object]) -> dict[str, SpotInstrument]:
    symbols = _symbols(payload, "spot")
    parsed: dict[str, SpotInstrument] = {}
    for raw in symbols:
        symbol = _upper(raw.get("symbol"))
        if not symbol:
            continue
        spot_allowed_value = raw.get("isSpotTradingAllowed", raw.get("spotTradingAllowed", True))
        parsed[symbol] = SpotInstrument(
            symbol=symbol,
            base_asset=_upper(raw.get("baseAsset")),
            quote_asset=_upper(raw.get("quoteAsset")),
            status=_upper(raw.get("status")),
            spot_trading_allowed=bool(spot_allowed_value),
        )
    return parsed


def parse_futures_exchange_info(payload: Mapping[str, object]) -> dict[str, FuturesInstrument]:
    symbols = _symbols(payload, "futures")
    parsed: dict[str, FuturesInstrument] = {}
    for raw in symbols:
        symbol = _upper(raw.get("symbol"))
        if not symbol:
            continue
        parsed[symbol] = FuturesInstrument(
            symbol=symbol,
            pair=_upper(raw.get("pair")) or symbol,
            base_asset=_upper(raw.get("baseAsset")),
            quote_asset=_upper(raw.get("quoteAsset")),
            margin_asset=_upper(raw.get("marginAsset")),
            contract_type=_upper(raw.get("contractType")),
            status=_upper(raw.get("status")),
        )
    return parsed


def _symbols(payload: Mapping[str, object], label: str) -> tuple[Mapping[str, object], ...]:
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        raise BinanceUnavailableError(f"Binance {label} exchangeInfo payload has no symbols list.")

    result: list[Mapping[str, object]] = []
    for item in raw_symbols:
        if isinstance(item, Mapping):
            result.append(cast(Mapping[str, object], item))
    return tuple(result)


def _upper(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.upper().strip()

