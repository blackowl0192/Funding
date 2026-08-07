from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from funding_terminal.domain.enums import ExecutionMode, MappingStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AssetInput:
    raw_symbol: str
    base_asset: str
    enabled: bool = True
    row_number: int | None = None


@dataclass(frozen=True, slots=True)
class SpotInstrument:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    spot_trading_allowed: bool

    @property
    def is_active(self) -> bool:
        return self.status == "TRADING" and self.spot_trading_allowed


@dataclass(frozen=True, slots=True)
class FuturesInstrument:
    symbol: str
    pair: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    contract_type: str
    status: str

    @property
    def is_active_perpetual_usdt(self) -> bool:
        return (
            self.status == "TRADING"
            and self.contract_type == "PERPETUAL"
            and self.quote_asset == "USDT"
            and self.margin_asset == "USDT"
        )


@dataclass(frozen=True, slots=True)
class InstrumentPair:
    base_asset: str
    spot: SpotInstrument | None
    futures: FuturesInstrument | None
    mapping_status: MappingStatus
    mapping_reason: str
    strategy_eligible: bool


@dataclass(frozen=True, slots=True)
class UniverseEntry:
    base_asset: str
    spot_symbol: str | None
    futures_symbol: str | None
    spot_status: str | None
    futures_status: str | None
    mapping_status: MappingStatus
    mapping_reason: str
    strategy_eligible: bool
    enabled: bool = True
    exchange: str = "BINANCE"
    last_checked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ImportResult:
    filename: str
    file_type: str
    total_rows: int
    unique_assets: int
    matched_count: int
    rejected_count: int
    duplicate_count: int
    invalid_count: int
    entries: tuple[UniverseEntry, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TradingSettings:
    total_capital: Decimal
    spot_budget: Decimal
    futures_margin_budget: Decimal
    futures_leverage: int
    quote_asset: str
    spot_maker_base_fee: Decimal
    spot_taker_base_fee: Decimal
    futures_maker_base_fee: Decimal
    futures_taker_base_fee: Decimal
    fee_discount_rate: Decimal
    default_execution_mode: ExecutionMode

    @property
    def free_reserve(self) -> Decimal:
        return self.total_capital - self.spot_budget - self.futures_margin_budget

    @property
    def max_futures_notional(self) -> Decimal:
        return self.futures_margin_budget * Decimal(self.futures_leverage)

    @property
    def max_hedged_notional(self) -> Decimal:
        return min(self.spot_budget, self.max_futures_notional)

    @property
    def capital_utilization_ratio(self) -> Decimal:
        if self.total_capital == 0:
            return Decimal("0")
        return (self.spot_budget + self.futures_margin_budget) / self.total_capital

    @property
    def effective_spot_maker_fee(self) -> Decimal:
        return self._effective_fee(self.spot_maker_base_fee)

    @property
    def effective_spot_taker_fee(self) -> Decimal:
        return self._effective_fee(self.spot_taker_base_fee)

    @property
    def effective_futures_maker_fee(self) -> Decimal:
        return self._effective_fee(self.futures_maker_base_fee)

    @property
    def effective_futures_taker_fee(self) -> Decimal:
        return self._effective_fee(self.futures_taker_base_fee)

    def _effective_fee(self, base_fee: Decimal) -> Decimal:
        return base_fee * (Decimal("1") - self.fee_discount_rate)


@dataclass(frozen=True, slots=True)
class ExchangeMetadata:
    spot_symbols: Mapping[str, SpotInstrument]
    futures_symbols: Mapping[str, FuturesInstrument]
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class DashboardStats:
    total_symbols: int
    eligible_symbols: int
    enabled_symbols: int
    rejected_symbols: int
    last_import_at: datetime | None
    settings: TradingSettings


@dataclass(frozen=True, slots=True)
class SymbolPage:
    entries: tuple[UniverseEntry, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 1
        return ((self.total - 1) // self.page_size) + 1

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages
