from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import uvicorn

from funding_terminal.config import Settings, get_settings
from funding_terminal.db.database import Database
from funding_terminal.db.migrations import MigrationRunner
from funding_terminal.domain.errors import FundingTerminalError
from funding_terminal.domain.models import DashboardStats, TradingSettings
from funding_terminal.exchange.binance.client import BinancePublicClient
from funding_terminal.main import setup_logging
from funding_terminal.repositories.funding_repository import (
    FundingCurrentRepository,
    FundingEventRepository,
    FundingStatisticsRepository,
    FundingSyncRepository,
)
from funding_terminal.repositories.import_repository import ImportRepository
from funding_terminal.repositories.settings_repository import SettingsRepository
from funding_terminal.repositories.symbol_repository import SymbolRepository
from funding_terminal.services.funding_service import (
    FundingAnalyticsService,
    FundingCurrentService,
    FundingHistoryService,
    FundingReportService,
    FundingSyncService,
    format_funding_report_lines,
)
from funding_terminal.services.import_service import ImportService
from funding_terminal.services.settings_service import format_decimal
from funding_terminal.services.universe_service import UniverseService


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings)

    if args.command == "run":
        try:
            asyncio.run(_check_run_database(settings))
        except FundingTerminalError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        uvicorn.run(
            "funding_terminal.main:create_app",
            factory=True,
            host=settings.app_host,
            port=settings.app_port,
            reload=settings.app_debug,
        )
        return 0

    try:
        return asyncio.run(_run_async(args, settings))
    except FundingTerminalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m funding_terminal")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run")
    subparsers.add_parser("migrate")
    subparsers.add_parser("check-db")
    subparsers.add_parser("check-binance")
    import_parser = subparsers.add_parser("import-universe")
    import_parser.add_argument("path")
    subparsers.add_parser("refresh-universe")
    subparsers.add_parser("status")
    sync_funding_parser = subparsers.add_parser("sync-funding")
    sync_funding_parser.add_argument("--days", type=int, default=30)
    sync_funding_parser.add_argument("--symbols", default="")
    sync_funding_parser.add_argument("--current-only", action="store_true")
    sync_funding_parser.add_argument("--history-only", action="store_true")
    subparsers.add_parser("funding-status")
    funding_report_parser = subparsers.add_parser("funding-report")
    funding_report_parser.add_argument("--window", type=int, choices=[7, 14, 30], default=14)
    funding_report_parser.add_argument("--limit", type=int, default=20)
    funding_report_parser.add_argument(
        "--sort",
        choices=["stability", "mean", "cumulative"],
        default="stability",
    )
    return parser


async def _check_run_database(settings: Settings) -> None:
    db = Database(settings.database_url)
    await db.connect()
    await db.close()


async def _run_async(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "migrate":
        applied = await MigrationRunner(settings).run()
        if applied:
            for migration in applied:
                print(f"applied migration: {migration.name}")
        else:
            print("migrations: up to date")
        return 0

    if args.command == "check-binance":
        client = BinancePublicClient(settings)
        try:
            spot_ok, futures_ok = await asyncio.gather(client.check_spot(), client.check_futures())
        finally:
            await client.aclose()
        print(f"binance_spot: {'OK' if spot_ok else 'ERROR'}")
        print(f"binance_futures: {'OK' if futures_ok else 'ERROR'}")
        return 0 if spot_ok and futures_ok else 1

    db = Database(settings.database_url)
    await db.connect()
    client = BinancePublicClient(settings)
    try:
        if args.command == "check-db":
            ok = await db.health_check()
            print(f"database: {'OK' if ok else 'ERROR'}")
            return 0 if ok else 1
        if args.command == "import-universe":
            return await _import_universe(settings, db, client, Path(args.path))
        if args.command == "refresh-universe":
            entries = await UniverseService(SymbolRepository(db), client).refresh_universe()
            print(f"refreshed_symbols: {len(entries)}")
            return 0
        if args.command == "sync-funding":
            return await _sync_funding(db, client, args)
        if args.command == "funding-status":
            return await _funding_status(db)
        if args.command == "funding-report":
            return await _funding_report(db, args)
        if args.command == "status":
            return await _status(db, client)
    finally:
        await client.aclose()
        await db.close()
    return 1


async def _import_universe(
    settings: Settings,
    db: Database,
    client: BinancePublicClient,
    path: Path,
) -> int:
    try:
        filename, content = await asyncio.to_thread(_read_import_file, path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1
    result = await ImportService(
        settings,
        SymbolRepository(db),
        ImportRepository(db),
        client,
    ).import_universe(filename, content)
    print(f"total_rows: {result.total_rows}")
    print(f"matched: {result.matched_count}")
    print(f"rejected: {result.rejected_count}")
    print(f"duplicates: {result.duplicate_count}")
    print(f"invalid: {result.invalid_count}")
    return 0


def _read_import_file(path: Path) -> tuple[str, bytes]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    return path.name, path.read_bytes()


async def _sync_funding(
    db: Database,
    client: BinancePublicClient,
    args: argparse.Namespace,
) -> int:
    if args.current_only and args.history_only:
        print("error: --current-only and --history-only are mutually exclusive", file=sys.stderr)
        return 2
    if args.days < 1:
        print("error: --days must be positive", file=sys.stderr)
        return 2
    service = _funding_sync_service(db, client)
    result = await service.sync_funding_universe(
        days=args.days,
        symbols=_parse_symbol_list(args.symbols),
        current_only=args.current_only,
        history_only=args.history_only,
    )
    print(f"total: {result.total}")
    print(f"success: {result.success}")
    print(f"failed: {result.failed}")
    print(f"events_inserted: {result.events_inserted}")
    print(f"events_existing: {result.events_existing}")
    print(f"statistics_updated: {result.statistics_updated}")
    print(f"current_updated: {result.current_updated}")
    for error in result.errors:
        print(f"error {error.symbol}: {error.error}")
    return 0 if result.failed == 0 else 1


async def _funding_status(db: Database) -> int:
    summary = await FundingReportService(
        SettingsRepository(db),
        FundingStatisticsRepository(db),
        FundingSyncRepository(db),
    ).status_summary()
    print(f"tracked: {summary.tracked}")
    print(f"history_synced: {summary.history_synced}")
    print(f"failed: {summary.failed}")
    print(f"current_positive: {summary.current_positive}")
    print(f"current_negative: {summary.current_negative}")
    print(f"stale: {summary.stale}")
    print(f"last_sync: {summary.last_sync or 'never'}")
    return 0


async def _funding_report(db: Database, args: argparse.Namespace) -> int:
    settings_repo = SettingsRepository(db)
    settings = await settings_repo.get()
    rows = await FundingReportService(
        settings_repo,
        FundingStatisticsRepository(db),
        FundingSyncRepository(db),
    ).table_rows(window_days=args.window, sort=args.sort, direction="desc", limit=args.limit)
    for line in format_funding_report_lines(rows, quote_asset=settings.quote_asset):
        print(line)
    return 0


def _funding_sync_service(db: Database, client: BinancePublicClient) -> FundingSyncService:
    events = FundingEventRepository(db)
    current = FundingCurrentRepository(db)
    statistics = FundingStatisticsRepository(db)
    sync_state = FundingSyncRepository(db)
    analytics = FundingAnalyticsService(events, current, statistics)
    history = FundingHistoryService(client, events, sync_state, analytics)
    current_service = FundingCurrentService(client, current)
    return FundingSyncService(sync_state, history, current_service)


def _parse_symbol_list(raw_symbols: str) -> tuple[str, ...]:
    if not raw_symbols.strip():
        return ()
    return tuple(symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip())


async def _status(db: Database, client: BinancePublicClient) -> int:
    settings_repo = SettingsRepository(db)
    symbol_repo = SymbolRepository(db)
    trading_settings = await settings_repo.get()
    stats = await symbol_repo.dashboard_stats(trading_settings)
    database_ok, spot_ok, futures_ok = await asyncio.gather(
        db.health_check(),
        client.check_spot(),
        client.check_futures(),
    )
    for line in format_status_lines(stats, trading_settings, database_ok, spot_ok, futures_ok):
        print(line)
    return 0 if database_ok and spot_ok and futures_ok else 1


def format_status_lines(
    stats: DashboardStats,
    settings: TradingSettings,
    database_ok: bool,
    spot_ok: bool,
    futures_ok: bool,
) -> list[str]:
    quote_asset = settings.quote_asset
    return [
        f"database: {'OK' if database_ok else 'ERROR'}",
        f"binance_spot: {'OK' if spot_ok else 'ERROR'}",
        f"binance_futures: {'OK' if futures_ok else 'ERROR'}",
        f"total_symbols: {stats.total_symbols}",
        f"eligible_symbols: {stats.eligible_symbols}",
        f"enabled_symbols: {stats.enabled_symbols}",
        f"rejected_symbols: {stats.rejected_symbols}",
        "capital:",
        f"  total: {format_decimal(settings.total_capital)} {quote_asset}",
        f"  spot_budget: {format_decimal(settings.spot_budget)} {quote_asset}",
        "  futures_margin_budget: "
        f"{format_decimal(settings.futures_margin_budget)} {quote_asset}",
        f"  free_reserve: {format_decimal(settings.free_reserve)} {quote_asset}",
        f"  leverage: {settings.futures_leverage}x",
        f"  futures_capacity: {format_decimal(settings.max_futures_notional)} {quote_asset}",
        f"  max_hedged_notional: {format_decimal(settings.max_hedged_notional)} {quote_asset}",
        "fees:",
        f"  discount: {format_decimal(settings.fee_discount_rate * 100)}%",
        f"  spot_maker_base: {format_decimal(settings.spot_maker_base_fee * 100)}%",
        f"  spot_maker_effective: {format_decimal(settings.effective_spot_maker_fee * 100)}%",
        f"  spot_taker_base: {format_decimal(settings.spot_taker_base_fee * 100)}%",
        f"  spot_taker_effective: {format_decimal(settings.effective_spot_taker_fee * 100)}%",
        f"  futures_maker_base: {format_decimal(settings.futures_maker_base_fee * 100)}%",
        "  futures_maker_effective: "
        f"{format_decimal(settings.effective_futures_maker_fee * 100)}%",
        f"  futures_taker_base: {format_decimal(settings.futures_taker_base_fee * 100)}%",
        "  futures_taker_effective: "
        f"{format_decimal(settings.effective_futures_taker_fee * 100)}%",
        f"last_import: {stats.last_import_at or 'never'}",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
