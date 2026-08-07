from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from funding_terminal.config import Settings
from funding_terminal.db.database import Database
from funding_terminal.domain.errors import FundingTerminalError, SettingsValidationError
from funding_terminal.domain.funding import (
    ensure_utc,
    format_money,
    format_rate_percent,
    format_ratio_percent,
)
from funding_terminal.exchange.binance.client import BinancePublicClient
from funding_terminal.repositories.funding_repository import (
    FundingCurrentRepository,
    FundingEventRepository,
    FundingStatisticsRepository,
    FundingSyncRepository,
)
from funding_terminal.repositories.import_repository import ImportRepository
from funding_terminal.repositories.settings_repository import SettingsRepository
from funding_terminal.repositories.symbol_repository import PAGE_SIZE, SymbolRepository
from funding_terminal.services.funding_service import (
    FundingAnalyticsService,
    FundingCurrentService,
    FundingHistoryService,
    FundingReportService,
    FundingSyncService,
)
from funding_terminal.services.import_service import ImportService
from funding_terminal.services.settings_service import SettingsService, format_decimal
from funding_terminal.services.universe_service import UniverseService

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


@dataclass(frozen=True, slots=True)
class WebServices:
    settings: Settings
    db: Database
    binance_client: BinancePublicClient
    symbols: SymbolRepository
    imports: ImportRepository
    settings_repo: SettingsRepository


def _services(request: Request) -> WebServices:
    db = request.app.state.db
    return WebServices(
        settings=request.app.state.settings,
        db=db,
        binance_client=request.app.state.binance_client,
        symbols=SymbolRepository(db),
        imports=ImportRepository(db),
        settings_repo=SettingsRepository(db),
    )


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _percent(value: Decimal) -> str:
    return format_decimal(value * Decimal("100"))


def _rate(value: Decimal | None) -> str:
    return format_rate_percent(value)


def _ratio(value: Decimal | None) -> str:
    return format_ratio_percent(value)


def _money(value: Decimal | None, quote_asset: str = "USDT") -> str:
    return format_money(value, quote_asset)


def _utc(value: datetime | None) -> str:
    if value is None:
        return "-"
    return ensure_utc(value).strftime("%Y-%m-%d %H:%M UTC")


def _streak_duration(count: int, interval_hours: Decimal | None) -> str:
    if count <= 0:
        return "0 events"
    if interval_hours is None or interval_hours <= 0:
        return f"{count} events"
    days = Decimal(count) * interval_hours / Decimal("24")
    return f"{count} events (~{format_decimal(days)} days)"


templates.env.filters["percent"] = _percent
templates.env.filters["decimal"] = format_decimal
templates.env.filters["rate"] = _rate
templates.env.filters["ratio"] = _ratio
templates.env.filters["money"] = _money
templates.env.filters["utc"] = _utc
templates.env.filters["streak"] = _streak_duration


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    services = _services(request)
    trading_settings = await services.settings_repo.get()
    stats = await services.symbols.dashboard_stats(trading_settings)
    database_ok, spot_ok, futures_ok = await asyncio.gather(
        services.db.health_check(),
        services.binance_client.check_spot(),
        services.binance_client.check_futures(),
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "stats": stats,
            "database_status": _status(database_ok),
            "spot_status": _status(spot_ok),
            "futures_status": _status(futures_ok),
        },
    )


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    services = _services(request)
    database_ok, spot_ok, futures_ok = await asyncio.gather(
        services.db.health_check(),
        services.binance_client.check_spot(),
        services.binance_client.check_futures(),
    )
    overall = "ok" if database_ok and spot_ok and futures_ok else "degraded"
    return JSONResponse(
        {
            "status": overall,
            "database": _status(database_ok),
            "binance_spot": _status(spot_ok),
            "binance_futures": _status(futures_ok),
        }
    )


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "import.html",
        {"active": "import", "result": None, "error": None},
    )


@router.post("/import", response_class=HTMLResponse)
async def import_upload(request: Request, file: UploadFile = File(...)) -> HTMLResponse:
    services = _services(request)
    result = None
    error = None
    status_code = 200
    try:
        content = await file.read()
        result = await ImportService(
            services.settings,
            services.symbols,
            services.imports,
            services.binance_client,
        ).import_universe(file.filename or "upload", content)
    except FundingTerminalError as exc:
        error = str(exc)
        status_code = 400

    template = "partials/import_result.html" if _is_htmx(request) else "import.html"
    return templates.TemplateResponse(
        request,
        template,
        {"active": "import", "result": result, "error": error},
        status_code=status_code,
    )


@router.get("/symbols", response_class=HTMLResponse)
async def symbols_page(
    request: Request,
    search: str = "",
    filter_name: str = Query("all", alias="filter"),
    sort: str = "funding_14d_stability",
    direction: str = "desc",
    page: int = 1,
) -> HTMLResponse:
    services = _services(request)
    settings = await services.settings_repo.get()
    symbols = await services.symbols.list_symbols(
        search=search,
        filter_name=filter_name,
        sort=sort,
        direction=direction,
        page=page,
        page_size=PAGE_SIZE,
    )
    funding_rows = await FundingReportService(
        services.settings_repo,
        FundingStatisticsRepository(services.db),
        FundingSyncRepository(services.db),
    ).table_rows(window_days=14, sort="base_asset", direction="asc", limit=1000)
    context = {
        "active": "symbols",
        "symbols": symbols,
        "funding_by_asset": {row.base_asset: row for row in funding_rows},
        "quote_asset": settings.quote_asset,
        "search": search,
        "filter_name": filter_name,
        "sort": sort,
        "direction": direction,
        "message": None,
        "error": None,
    }
    template = "partials/symbol_table.html" if _is_htmx(request) else "symbols.html"
    return templates.TemplateResponse(request, template, context)


@router.get("/funding", response_class=HTMLResponse)
async def funding_page(
    request: Request,
    sort: str = "stability",
    direction: str = "desc",
) -> HTMLResponse:
    context = await _funding_context(request, sort=sort, direction=direction)
    return templates.TemplateResponse(request, "funding.html", context)


@router.post("/funding/refresh", response_class=HTMLResponse)
async def refresh_funding(request: Request) -> Response:
    result = None
    error = None
    try:
        result = await _funding_sync_service(request).sync_funding_universe(days=30)
    except FundingTerminalError as exc:
        error = str(exc)
    if not _is_htmx(request):
        return RedirectResponse("/funding", status_code=303)
    context = await _funding_context(request, result=result, error=error)
    return templates.TemplateResponse(request, "partials/funding_content.html", context)


@router.get("/funding/{base_asset}", response_class=HTMLResponse)
async def funding_detail(request: Request, base_asset: str) -> HTMLResponse:
    services = _services(request)
    sync_repo = FundingSyncRepository(services.db)
    symbol = await sync_repo.get_symbol(base_asset)
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"{base_asset.upper()} not found.")
    settings = await services.settings_repo.get()
    statistics_repo = FundingStatisticsRepository(services.db)
    event_repo = FundingEventRepository(services.db)
    current_repo = FundingCurrentRepository(services.db)
    current = await current_repo.get(symbol.symbol_id)
    statistics = await statistics_repo.list_by_symbol(symbol.symbol_id)
    events = await event_repo.list_events(
        symbol.symbol_id,
        start_at=datetime.now(UTC) - timedelta(days=30),
        limit=120,
    )
    stats_by_window = {item.window_days: item for item in statistics}
    return templates.TemplateResponse(
        request,
        "funding_detail.html",
        {
            "active": "funding",
            "symbol": symbol,
            "settings": settings,
            "current": current,
            "stats_by_window": stats_by_window,
            "events": tuple(reversed(events)),
            "history_chart": _history_chart_points(events),
            "quote_asset": settings.quote_asset,
            "message": None,
            "error": None,
        },
    )


@router.post("/funding/{base_asset}/refresh", response_class=HTMLResponse)
async def refresh_symbol_funding(request: Request, base_asset: str) -> Response:
    try:
        await _funding_sync_service(request).sync_funding_universe(
            days=30,
            symbols=(base_asset,),
        )
    except FundingTerminalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/funding/{base_asset.upper()}", status_code=303)


@router.post("/symbols/{base_asset}/enable", response_class=HTMLResponse)
async def enable_symbol(request: Request, base_asset: str) -> Response:
    return await _toggle_symbol(request, base_asset, enabled=True)


@router.post("/symbols/{base_asset}/disable", response_class=HTMLResponse)
async def disable_symbol(request: Request, base_asset: str) -> Response:
    return await _toggle_symbol(request, base_asset, enabled=False)


@router.post("/symbols/{base_asset}/refresh", response_class=HTMLResponse)
async def refresh_symbol(request: Request, base_asset: str) -> Response:
    services = _services(request)
    message = None
    error = None
    try:
        await UniverseService(services.symbols, services.binance_client).refresh_symbol(base_asset)
        message = f"{base_asset.upper()} refreshed."
    except FundingTerminalError as exc:
        error = str(exc)
    if not _is_htmx(request):
        return RedirectResponse("/symbols", status_code=303)
    return await _symbols_partial(request, message=message, error=error)


@router.post("/symbols/refresh-all", response_class=HTMLResponse)
async def refresh_all_symbols(request: Request) -> Response:
    services = _services(request)
    message = None
    error = None
    try:
        entries = await UniverseService(
            services.symbols,
            services.binance_client,
        ).refresh_universe()
        message = f"Refreshed {len(entries)} symbols."
    except FundingTerminalError as exc:
        error = str(exc)
    if not _is_htmx(request):
        return RedirectResponse("/symbols", status_code=303)
    return await _symbols_partial(request, message=message, error=error)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    services = _services(request)
    trading_settings = await services.settings_repo.get()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active": "settings",
            "settings": trading_settings,
            "message": None,
            "error": None,
        },
    )


@router.post("/settings", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    total_capital: str = Form(...),
    spot_budget: str = Form(...),
    futures_margin_budget: str = Form(...),
    futures_leverage: str = Form(...),
    quote_asset: str = Form(...),
    spot_maker_base_fee: str = Form(...),
    spot_taker_base_fee: str = Form(...),
    futures_maker_base_fee: str = Form(...),
    futures_taker_base_fee: str = Form(...),
    fee_discount: str = Form(...),
) -> Response:
    services = _services(request)
    current_settings = await services.settings_repo.get()
    message = None
    error = None
    status_code = 200
    try:
        next_settings = SettingsService().build_settings(
            total_capital=total_capital,
            spot_budget=spot_budget,
            futures_margin_budget=futures_margin_budget,
            futures_leverage=futures_leverage,
            quote_asset=quote_asset,
            spot_maker_base_fee_percent=spot_maker_base_fee,
            spot_taker_base_fee_percent=spot_taker_base_fee,
            futures_maker_base_fee_percent=futures_maker_base_fee,
            futures_taker_base_fee_percent=futures_taker_base_fee,
            fee_discount_percent=fee_discount,
            default_execution_mode=current_settings.default_execution_mode.value,
        )
        await services.settings_repo.update(next_settings)
        current_settings = next_settings
        message = "Settings saved."
    except SettingsValidationError as exc:
        error = str(exc)
        status_code = 400

    if not _is_htmx(request) and error is None:
        return RedirectResponse("/settings", status_code=303)
    template = "partials/settings_form.html" if _is_htmx(request) else "settings.html"
    return templates.TemplateResponse(
        request,
        template,
        {
            "active": "settings",
            "settings": current_settings,
            "message": message,
            "error": error,
        },
        status_code=status_code,
    )


async def _toggle_symbol(
    request: Request,
    base_asset: str,
    *,
    enabled: bool,
) -> Response:
    services = _services(request)
    await services.symbols.set_enabled(base_asset, enabled)
    if not _is_htmx(request):
        return RedirectResponse("/symbols", status_code=303)
    action = "enabled" if enabled else "disabled"
    return await _symbols_partial(request, message=f"{base_asset.upper()} {action}.", error=None)


async def _symbols_partial(
    request: Request,
    *,
    message: str | None,
    error: str | None,
) -> HTMLResponse:
    services = _services(request)
    settings = await services.settings_repo.get()
    symbols = await services.symbols.list_symbols(page_size=PAGE_SIZE)
    funding_rows = await FundingReportService(
        services.settings_repo,
        FundingStatisticsRepository(services.db),
        FundingSyncRepository(services.db),
    ).table_rows(window_days=14, sort="base_asset", direction="asc", limit=1000)
    return templates.TemplateResponse(
        request,
        "partials/symbol_table.html",
        {
            "active": "symbols",
            "symbols": symbols,
            "funding_by_asset": {row.base_asset: row for row in funding_rows},
            "quote_asset": settings.quote_asset,
            "search": "",
            "filter_name": "all",
            "sort": "funding_14d_stability",
            "direction": "desc",
            "message": message,
            "error": error,
        },
    )


def _status(ok: bool) -> str:
    return "ok" if ok else "error"


async def _funding_context(
    request: Request,
    *,
    sort: str = "stability",
    direction: str = "desc",
    result: object | None = None,
    error: str | None = None,
) -> dict[str, object]:
    services = _services(request)
    settings = await services.settings_repo.get()
    report = FundingReportService(
        services.settings_repo,
        FundingStatisticsRepository(services.db),
        FundingSyncRepository(services.db),
    )
    summary = await report.status_summary()
    rows = await report.table_rows(window_days=14, sort=sort, direction=direction, limit=200)
    return {
        "active": "funding",
        "summary": summary,
        "rows": rows,
        "settings": settings,
        "quote_asset": settings.quote_asset,
        "sort": sort,
        "direction": direction,
        "result": result,
        "message": _funding_result_message(result) if result else None,
        "error": error,
    }


def _funding_sync_service(request: Request) -> FundingSyncService:
    services = _services(request)
    event_repo = FundingEventRepository(services.db)
    current_repo = FundingCurrentRepository(services.db)
    statistics_repo = FundingStatisticsRepository(services.db)
    sync_repo = FundingSyncRepository(services.db)
    analytics = FundingAnalyticsService(event_repo, current_repo, statistics_repo)
    history = FundingHistoryService(services.binance_client, event_repo, sync_repo, analytics)
    current = FundingCurrentService(services.binance_client, current_repo)
    return FundingSyncService(sync_repo, history, current)


def _funding_result_message(result: object | None) -> str | None:
    if result is None:
        return None
    success = getattr(result, "success", 0)
    failed = getattr(result, "failed", 0)
    inserted = getattr(result, "events_inserted", 0)
    existing = getattr(result, "events_existing", 0)
    current = getattr(result, "current_updated", 0)
    return (
        f"Funding refreshed. Success: {success}, failed: {failed}, "
        f"events inserted: {inserted}, existing: {existing}, current updated: {current}."
    )


def _history_chart_points(events: tuple[object, ...]) -> tuple[dict[str, object], ...]:
    points: list[dict[str, object]] = []
    for event in events[-90:]:
        if not hasattr(event, "funding_rate") or not hasattr(event, "funding_time"):
            continue
        rate = event.funding_rate
        if not isinstance(rate, Decimal):
            continue
        percent = rate * Decimal("100")
        height = min(abs(percent) * Decimal("400"), Decimal("100"))
        points.append(
            {
                "time": _utc(event.funding_time),
                "rate": rate,
                "height": height,
                "positive": rate >= 0,
            }
        )
    return tuple(points)
