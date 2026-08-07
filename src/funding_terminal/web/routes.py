from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from funding_terminal.config import Settings
from funding_terminal.db.database import Database
from funding_terminal.domain.errors import FundingTerminalError, SettingsValidationError
from funding_terminal.exchange.binance.client import BinancePublicClient
from funding_terminal.repositories.import_repository import ImportRepository
from funding_terminal.repositories.settings_repository import SettingsRepository
from funding_terminal.repositories.symbol_repository import PAGE_SIZE, SymbolRepository
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


templates.env.filters["percent"] = _percent
templates.env.filters["decimal"] = format_decimal


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
    sort: str = "base_asset",
    direction: str = "asc",
    page: int = 1,
) -> HTMLResponse:
    services = _services(request)
    symbols = await services.symbols.list_symbols(
        search=search,
        filter_name=filter_name,
        sort=sort,
        direction=direction,
        page=page,
        page_size=PAGE_SIZE,
    )
    context = {
        "active": "symbols",
        "symbols": symbols,
        "search": search,
        "filter_name": filter_name,
        "sort": sort,
        "direction": direction,
        "message": None,
        "error": None,
    }
    template = "partials/symbol_table.html" if _is_htmx(request) else "symbols.html"
    return templates.TemplateResponse(request, template, context)


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
    symbols = await services.symbols.list_symbols(page_size=PAGE_SIZE)
    return templates.TemplateResponse(
        request,
        "partials/symbol_table.html",
        {
            "active": "symbols",
            "symbols": symbols,
            "search": "",
            "filter_name": "all",
            "sort": "base_asset",
            "direction": "asc",
            "message": message,
            "error": error,
        },
    )


def _status(ok: bool) -> str:
    return "ok" if ok else "error"
