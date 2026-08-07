from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from funding_terminal.domain.errors import DatabaseUnavailableError

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if not self._database_url:
            raise DatabaseUnavailableError("DATABASE_URL is not configured.")
        if "CHANGE_ME" in self._database_url:
            raise DatabaseUnavailableError(
                "DATABASE_URL contains CHANGE_ME. Replace it with your PostgreSQL password in .env."
            )
        if self._pool is None:
            logger.info("DB connect")
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=self._database_url,
                    min_size=1,
                    max_size=10,
                )
            except asyncpg.InvalidPasswordError as exc:
                raise DatabaseUnavailableError(
                    "Database authentication failed. Check the PostgreSQL password in .env."
                ) from exc
            except asyncpg.InvalidCatalogNameError as exc:
                raise DatabaseUnavailableError(
                    "Database does not exist. Create funding_terminal or run setup_local.ps1."
                ) from exc
            except OSError as exc:
                raise DatabaseUnavailableError(
                    "Database host or port is unavailable. Check PostgreSQL service and port 5432."
                ) from exc
            except Exception as exc:
                raise DatabaseUnavailableError("Database connection failed.") from exc

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def health_check(self) -> bool:
        try:
            value = await self.fetchval("SELECT 1")
        except Exception:
            logger.exception("DB health check failed")
            return False
        return value == 1

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        pool = self._require_pool()
        async with pool.acquire() as connection, connection.transaction():
            yield connection

    async def fetch(self, query: str, *args: object) -> Sequence[asyncpg.Record]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            return await connection.fetch(query, *args)

    async def fetchrow(self, query: str, *args: object) -> asyncpg.Record | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: object) -> Any:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            return await connection.fetchval(query, *args)

    async def execute(self, query: str, *args: object) -> str:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            return await connection.execute(query, *args)

    async def executemany(self, query: str, args: Iterable[tuple[object, ...]]) -> None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            await connection.executemany(query, args)

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise DatabaseUnavailableError("Database pool is not connected.")
        return self._pool
