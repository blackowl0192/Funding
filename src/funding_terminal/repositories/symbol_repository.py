from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from funding_terminal.db.database import Database
from funding_terminal.domain.enums import MappingStatus
from funding_terminal.domain.errors import InvalidSymbolError
from funding_terminal.domain.models import (
    AssetInput,
    DashboardStats,
    SymbolPage,
    TradingSettings,
    UniverseEntry,
)

PAGE_SIZE = 50
FILTERS = {"all", "eligible", "rejected", "enabled", "disabled"}
SORT_COLUMNS = {
    "base_asset": "base_asset",
    "eligible": "strategy_eligible",
    "enabled": "enabled",
    "mapping_status": "mapping_status",
    "last_checked": "last_checked_at",
}


class SymbolRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_many(self, entries: tuple[UniverseEntry, ...]) -> None:
        if not entries:
            return
        await self._db.executemany(
            """
            INSERT INTO symbols (
                base_asset,
                spot_symbol,
                futures_symbol,
                spot_status,
                futures_status,
                mapping_status,
                mapping_reason,
                strategy_eligible,
                enabled,
                exchange,
                last_checked_at,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, COALESCE($11, NOW()), NOW())
            ON CONFLICT (exchange, base_asset) DO UPDATE SET
                spot_symbol = EXCLUDED.spot_symbol,
                futures_symbol = EXCLUDED.futures_symbol,
                spot_status = EXCLUDED.spot_status,
                futures_status = EXCLUDED.futures_status,
                mapping_status = EXCLUDED.mapping_status,
                mapping_reason = EXCLUDED.mapping_reason,
                strategy_eligible = EXCLUDED.strategy_eligible,
                enabled = EXCLUDED.enabled,
                last_checked_at = EXCLUDED.last_checked_at,
                updated_at = NOW()
            """,
            tuple(
                (
                    entry.base_asset,
                    entry.spot_symbol,
                    entry.futures_symbol,
                    entry.spot_status,
                    entry.futures_status,
                    entry.mapping_status.value,
                    entry.mapping_reason,
                    entry.strategy_eligible,
                    entry.enabled,
                    entry.exchange,
                    entry.last_checked_at,
                )
                for entry in entries
            ),
        )

    async def list_symbols(
        self,
        *,
        search: str = "",
        filter_name: str = "all",
        sort: str = "base_asset",
        direction: str = "asc",
        page: int = 1,
        page_size: int = PAGE_SIZE,
    ) -> SymbolPage:
        page = max(page, 1)
        page_size = min(max(page_size, 1), PAGE_SIZE)
        where, params = _where(search, filter_name)
        order_column = SORT_COLUMNS.get(sort, "base_asset")
        order_direction = "DESC" if direction.lower() == "desc" else "ASC"
        offset = (page - 1) * page_size

        count_sql = f"SELECT COUNT(*) FROM symbols {where}"
        total = int(await self._db.fetchval(count_sql, *params) or 0)

        rows = await self._db.fetch(
            f"""
            SELECT base_asset,
                   spot_symbol,
                   futures_symbol,
                   spot_status,
                   futures_status,
                   mapping_status,
                   mapping_reason,
                   strategy_eligible,
                   enabled,
                   exchange,
                   last_checked_at
            FROM symbols
            {where}
            ORDER BY {order_column} {order_direction}, base_asset ASC
            LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
            """,
            *params,
            page_size,
            offset,
        )
        return SymbolPage(
            entries=tuple(_entry_from_row(row) for row in rows),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_asset_inputs(self) -> tuple[AssetInput, ...]:
        rows = await self._db.fetch(
            """
            SELECT base_asset, enabled
            FROM symbols
            WHERE exchange = 'BINANCE'
              AND mapping_status <> 'INVALID_INPUT'
            ORDER BY base_asset
            """
        )
        return tuple(_asset_input_from_row(row) for row in rows)

    async def get_asset_input(self, base_asset: str) -> AssetInput:
        row = await self._db.fetchrow(
            """
            SELECT base_asset, enabled
            FROM symbols
            WHERE exchange = 'BINANCE' AND base_asset = $1
            """,
            base_asset.upper(),
        )
        if row is None:
            raise InvalidSymbolError(f"Symbol {base_asset.upper()} is not in the universe.")
        return AssetInput(
            raw_symbol=str(row["base_asset"]),
            base_asset=str(row["base_asset"]),
            enabled=bool(row["enabled"]),
        )

    async def set_enabled(self, base_asset: str, enabled: bool) -> None:
        await self._db.execute(
            """
            UPDATE symbols
            SET enabled = $2,
                updated_at = NOW()
            WHERE exchange = 'BINANCE' AND base_asset = $1
            """,
            base_asset.upper(),
            enabled,
        )

    async def dashboard_stats(self, settings: TradingSettings) -> DashboardStats:
        row = await self._db.fetchrow(
            """
            SELECT COUNT(*)::int AS total_symbols,
                   COUNT(*) FILTER (WHERE strategy_eligible)::int AS eligible_symbols,
                   COUNT(*) FILTER (WHERE enabled)::int AS enabled_symbols,
                   COUNT(*) FILTER (WHERE NOT strategy_eligible)::int AS rejected_symbols
            FROM symbols
            WHERE exchange = 'BINANCE'
            """
        )
        last_import_at = await self._db.fetchval(
            """
            SELECT completed_at
            FROM import_runs
            WHERE status = 'COMPLETED'
            ORDER BY completed_at DESC
            LIMIT 1
            """
        )
        if row is None:
            return DashboardStats(0, 0, 0, 0, last_import_at, settings)
        return DashboardStats(
            total_symbols=int(row["total_symbols"]),
            eligible_symbols=int(row["eligible_symbols"]),
            enabled_symbols=int(row["enabled_symbols"]),
            rejected_symbols=int(row["rejected_symbols"]),
            last_import_at=last_import_at,
            settings=settings,
        )


def _where(search: str, filter_name: str) -> tuple[str, list[object]]:
    clauses = ["exchange = 'BINANCE'"]
    params: list[object] = []
    if search.strip():
        params.append(f"%{search.strip().upper()}%")
        clauses.append(f"base_asset ILIKE ${len(params)}")
    normalized_filter = filter_name if filter_name in FILTERS else "all"
    if normalized_filter == "eligible":
        clauses.append("strategy_eligible = TRUE")
    elif normalized_filter == "rejected":
        clauses.append("strategy_eligible = FALSE")
    elif normalized_filter == "enabled":
        clauses.append("enabled = TRUE")
    elif normalized_filter == "disabled":
        clauses.append("enabled = FALSE")
    return "WHERE " + " AND ".join(clauses), params


def _asset_input_from_row(row: Mapping[str, object]) -> AssetInput:
    base_asset = str(row["base_asset"])
    return AssetInput(raw_symbol=base_asset, base_asset=base_asset, enabled=bool(row["enabled"]))


def _entry_from_row(row: Mapping[str, object]) -> UniverseEntry:
    return UniverseEntry(
        base_asset=str(row["base_asset"]),
        spot_symbol=_nullable_str(row["spot_symbol"]),
        futures_symbol=_nullable_str(row["futures_symbol"]),
        spot_status=_nullable_str(row["spot_status"]),
        futures_status=_nullable_str(row["futures_status"]),
        mapping_status=MappingStatus(str(row["mapping_status"])),
        mapping_reason=str(row["mapping_reason"] or ""),
        strategy_eligible=bool(row["strategy_eligible"]),
        enabled=bool(row["enabled"]),
        exchange=str(row["exchange"]),
        last_checked_at=_datetime_or_none(row["last_checked_at"]),
    )


def _nullable_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _datetime_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None
