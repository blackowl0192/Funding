from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from funding_terminal.config import Settings, get_settings
from funding_terminal.db.database import Database
from funding_terminal.exchange.binance.client import BinancePublicClient
from funding_terminal.web.routes import router


def setup_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings)
    logging.getLogger(__name__).info("app start")

    db = Database(settings.database_url)
    await db.connect()
    binance_client = BinancePublicClient(settings)

    app.state.settings = settings
    app.state.db = db
    app.state.binance_client = binance_client
    try:
        yield
    finally:
        await binance_client.aclose()
        await db.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Funding Arbitrage Terminal",
        debug=get_settings().app_debug,
        lifespan=lifespan,
    )
    static_dir = Path(__file__).resolve().parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(router)
    return app


app = create_app()
