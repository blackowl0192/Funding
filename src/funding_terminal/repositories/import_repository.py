from __future__ import annotations

from funding_terminal.db.database import Database
from funding_terminal.domain.enums import ImportRunStatus
from funding_terminal.domain.models import ImportResult


class ImportRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_result(self, result: ImportResult, status: ImportRunStatus) -> None:
        await self._db.execute(
            """
            INSERT INTO import_runs (
                filename,
                file_type,
                total_rows,
                unique_assets,
                matched_count,
                rejected_count,
                started_at,
                completed_at,
                status,
                error_message
            )
            VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW(), $7, NULL)
            """,
            result.filename,
            result.file_type,
            result.total_rows,
            result.unique_assets,
            result.matched_count,
            result.rejected_count,
            status.value,
        )

    async def record_failure(self, filename: str, error_message: str) -> None:
        await self._db.execute(
            """
            INSERT INTO import_runs (
                filename,
                started_at,
                completed_at,
                status,
                error_message
            )
            VALUES ($1, NOW(), NOW(), $2, $3)
            """,
            filename,
            ImportRunStatus.FAILED.value,
            error_message[:1000],
        )

    async def last_completed_at(self):
        return await self._db.fetchval(
            """
            SELECT completed_at
            FROM import_runs
            WHERE status = 'COMPLETED'
            ORDER BY completed_at DESC
            LIMIT 1
            """
        )

