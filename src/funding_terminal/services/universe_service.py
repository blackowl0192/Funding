from __future__ import annotations

import logging

from funding_terminal.domain.enums import MappingStatus
from funding_terminal.domain.models import (
    AssetInput,
    ExchangeMetadata,
    FuturesInstrument,
    InstrumentPair,
    SpotInstrument,
    UniverseEntry,
    utc_now,
)

logger = logging.getLogger(__name__)


class UniverseMatcher:
    def match_assets(
        self,
        assets: tuple[AssetInput, ...],
        metadata: ExchangeMetadata,
    ) -> tuple[UniverseEntry, ...]:
        return tuple(self.match_asset(asset, metadata) for asset in assets)

    def match_asset(self, asset: AssetInput, metadata: ExchangeMetadata) -> UniverseEntry:
        expected_symbol = f"{asset.base_asset}USDT"
        spot = metadata.spot_symbols.get(expected_symbol)
        futures = metadata.futures_symbols.get(expected_symbol)
        pair = self._pair_for(asset.base_asset, expected_symbol, spot, futures)
        return UniverseEntry(
            base_asset=asset.base_asset,
            spot_symbol=spot.symbol if spot else expected_symbol,
            futures_symbol=futures.symbol if futures else expected_symbol,
            spot_status=spot.status if spot else "MISSING",
            futures_status=futures.status if futures else "MISSING",
            mapping_status=pair.mapping_status,
            mapping_reason=pair.mapping_reason,
            strategy_eligible=pair.strategy_eligible,
            enabled=asset.enabled,
            last_checked_at=utc_now(),
        )

    def _pair_for(
        self,
        base_asset: str,
        expected_symbol: str,
        spot: SpotInstrument | None,
        futures: FuturesInstrument | None,
    ) -> InstrumentPair:
        if spot is None and futures is None:
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.SPOT_MISSING,
                f"{expected_symbol} is missing on Spot and USD-M Futures.",
                False,
            )
        if spot is None:
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.SPOT_MISSING,
                f"{expected_symbol} is missing on Spot.",
                False,
            )
        if futures is None:
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.FUTURES_MISSING,
                f"{expected_symbol} is missing on USD-M Futures.",
                False,
            )
        if spot.base_asset != base_asset or spot.quote_asset != "USDT":
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.METADATA_MISMATCH,
                "Spot metadata base or quote asset does not match expected BASE/USDT.",
                False,
            )
        if futures.base_asset != base_asset:
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.METADATA_MISMATCH,
                "Futures metadata base asset does not match expected base asset.",
                False,
            )
        if not spot.is_active:
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.SPOT_INACTIVE,
                "Spot symbol is not actively trading.",
                False,
            )
        if futures.quote_asset != "USDT" or futures.margin_asset != "USDT":
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.UNSUPPORTED_FUTURES,
                "Futures symbol is not a USDT quoted and USDT margined instrument.",
                False,
            )
        if futures.contract_type != "PERPETUAL":
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.UNSUPPORTED_FUTURES,
                "Futures symbol is not a perpetual contract.",
                False,
            )
        if not futures.is_active_perpetual_usdt:
            return InstrumentPair(
                base_asset,
                spot,
                futures,
                MappingStatus.FUTURES_INACTIVE,
                "Futures perpetual is not actively trading.",
                False,
            )
        return InstrumentPair(
            base_asset,
            spot,
            futures,
            MappingStatus.MATCHED,
            "Spot and USD-M perpetual metadata are active and consistent.",
            True,
        )


class UniverseService:
    def __init__(self, symbol_repository, binance_client) -> None:
        self._symbol_repository = symbol_repository
        self._binance_client = binance_client
        self._matcher = UniverseMatcher()

    async def refresh_universe(self) -> tuple[UniverseEntry, ...]:
        logger.info("refresh_universe started")
        assets = await self._symbol_repository.get_asset_inputs()
        if not assets:
            return ()
        metadata = await self._binance_client.load_exchange_metadata()
        entries = self._matcher.match_assets(assets, metadata)
        await self._symbol_repository.upsert_many(entries)
        logger.info("refresh_universe completed: %s symbols", len(entries))
        return entries

    async def refresh_symbol(self, base_asset: str) -> UniverseEntry:
        asset = await self._symbol_repository.get_asset_input(base_asset)
        metadata = await self._binance_client.load_exchange_metadata()
        entry = self._matcher.match_asset(asset, metadata)
        await self._symbol_repository.upsert_many((entry,))
        return entry
