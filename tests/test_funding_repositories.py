from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from funding_terminal.domain.funding import FundingCurrent, FundingEvent
from funding_terminal.repositories.funding_repository import (
    FundingCurrentRepository,
    FundingEventRepository,
    FundingStatisticsRepository,
    FundingSyncRepository,
)

NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)


class FakeFundingDb:
    def __init__(self) -> None:
        self.fetchvals = [1, None]
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.executemany_query = ""
        self.executemany_args: tuple[tuple[object, ...], ...] = ()

    async def fetchval(self, query: str, *args: object):
        return self.fetchvals.pop(0)

    async def fetchrow(self, query: str, *args: object):
        if "AS tracked" in query:
            return {
                "tracked": 2,
                "history_synced": 1,
                "failed": 1,
                "current_positive": 1,
                "current_negative": 1,
                "stale": 0,
                "last_sync": NOW,
            }
        return None

    async def fetch(self, query: str, *args: object):
        return []

    async def execute(self, query: str, *args: object) -> str:
        self.executed.append((query, args))
        return "OK"

    async def executemany(self, query: str, args):
        self.executemany_query = query
        self.executemany_args = tuple(args)


def funding_event(rate: str = "0.0001") -> FundingEvent:
    return FundingEvent(1, "BTCUSDT", NOW, Decimal(rate), Decimal("65000"))


@pytest.mark.asyncio
async def test_event_upsert_counts_inserted_and_existing() -> None:
    db = FakeFundingDb()
    repo = FundingEventRepository(db)  # type: ignore[arg-type]

    inserted, existing = await repo.upsert_events([funding_event(), funding_event()])

    assert inserted == 1
    assert existing == 1


@pytest.mark.asyncio
async def test_current_upsert_uses_conflict_update() -> None:
    db = FakeFundingDb()
    repo = FundingCurrentRepository(db)  # type: ignore[arg-type]

    updated = await repo.upsert_many(
        [
            FundingCurrent(
                symbol_id=1,
                futures_symbol="BTCUSDT",
                mark_price=Decimal("65000"),
                index_price=Decimal("64990"),
                last_funding_rate=Decimal("0.0001"),
                next_funding_time=NOW,
                interest_rate=Decimal("0.0001"),
                funding_interval_hours=Decimal("8"),
            )
        ]
    )

    assert updated == 1
    assert "ON CONFLICT (symbol_id) DO UPDATE" in db.executemany_query


@pytest.mark.asyncio
async def test_statistics_upsert_uses_symbol_window_key() -> None:
    from funding_terminal.domain.funding import calculate_funding_statistics

    db = FakeFundingDb()
    repo = FundingStatisticsRepository(db)  # type: ignore[arg-type]
    stats = calculate_funding_statistics([funding_event()], symbol_id=1, window_days=7, now=NOW)

    updated = await repo.upsert_many([stats])

    assert updated == 1
    assert "ON CONFLICT (symbol_id, window_days) DO UPDATE" in db.executemany_query


@pytest.mark.asyncio
async def test_sync_state_records_success_and_error() -> None:
    db = FakeFundingDb()
    repo = FundingSyncRepository(db)  # type: ignore[arg-type]

    await repo.mark_history_success(
        1,
        history_start_at=NOW,
        history_end_at=NOW,
        events_synced=3,
    )
    await repo.mark_error(1, "boom")

    assert "last_success_at" in db.executed[0][0]
    assert db.executed[1][1] == (1, "boom")


@pytest.mark.asyncio
async def test_status_summary_counts_funding_state() -> None:
    summary = await FundingSyncRepository(FakeFundingDb()).status_summary()  # type: ignore[arg-type]

    assert summary.tracked == 2
    assert summary.history_synced == 1
    assert summary.failed == 1
    assert summary.current_positive == 1
    assert summary.current_negative == 1
