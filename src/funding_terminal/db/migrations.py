from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from funding_terminal.config import Settings
from funding_terminal.domain.errors import DatabaseUnavailableError

logger = logging.getLogger(__name__)
MIGRATION_RE = re.compile(r"^(?P<version>\d+)_.*\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path


class MigrationRunner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self) -> list[Migration]:
        if not self._settings.database_url:
            raise DatabaseUnavailableError("DATABASE_URL is not configured.")
        if "CHANGE_ME" in self._settings.database_url:
            raise DatabaseUnavailableError(
                "DATABASE_URL contains CHANGE_ME. Replace it with your PostgreSQL password in .env."
            )
        migrations = discover_migrations(self._settings.migrations_dir)
        try:
            connection = await asyncpg.connect(dsn=self._settings.database_url)
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
            raise DatabaseUnavailableError("Database is unavailable for migrations.") from exc
        try:
            await self._ensure_table(connection)
            rows = await connection.fetch("SELECT version FROM schema_migrations")
            applied_versions = {int(row["version"]) for row in rows}
            applied_now: list[Migration] = []
            for migration in migrations:
                if migration.version in applied_versions:
                    continue
                logger.info("applying migration %s", migration.name)
                sql = migration.path.read_text(encoding="utf-8")
                async with connection.transaction():
                    await connection.execute(sql)
                    await connection.execute(
                        """
                        INSERT INTO schema_migrations(version, name)
                        VALUES ($1, $2)
                        """,
                        migration.version,
                        migration.name,
                    )
                applied_now.append(migration)
            return applied_now
        finally:
            await connection.close()

    async def _ensure_table(self, connection: asyncpg.Connection) -> None:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def discover_migrations(migrations_dir: Path) -> list[Migration]:
    if not migrations_dir.exists():
        return []
    migrations: list[Migration] = []
    for path in migrations_dir.glob("*.sql"):
        match = MIGRATION_RE.match(path.name)
        if match is None:
            continue
        migrations.append(Migration(version=int(match.group("version")), name=path.name, path=path))
    return sorted(migrations, key=lambda item: item.version)
