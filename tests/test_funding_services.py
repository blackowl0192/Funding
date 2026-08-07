from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from funding_terminal.domain.errors import BinanceUnavailableError
from funding_terminal.domain.funding import FundingCurrent, FundingEvent, FundingSymbol
from funding_terminal.services import funding_service
from funding_terminal.services.funding_service import (
    FundingCurrentService,
    FundingHistoryService,
    parse_funding_current,
    parse_funding_history_event,
)

NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
BTC = FundingSymbol(symbol_id=1, base_asset="BTC", futures_symbol="BTCUSDT")
ETH = FundingSymbol(symbol_id=2, base_asset="ETH", futures_symbol="ETHUSDT")


class FakeFundingClient:
    def __init__(self, pages: list[list[dict[str, object]]] | None = None) -> None:
        self.pages = pages or []
        self.history_calls: list[dict[str, object]] = []
        self.premium_calls = 0
        self.funding_info_calls = 0

    async def get_funding_rate_history(
        self,
        symbol: str,
        *,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ):
        self.history_calls.append(
            {
                "symbol": symbol,
                "start": start_time_ms,
                "end": end_time_ms,
                "limit": limit,
            }
        )
        if not self.pages:
            return []
        return self.pages.pop(0)

    async def get_premium_index(self, symbol: str | None = None):
        self.premium_calls += 1
        return [
            {
                "symbol": "BTCUSDT",
                "markPrice": "65000",
                "indexPrice": "64990",
                "lastFundingRate": "0.0001",
                "nextFundingTime": "1786104000000",
                "interestRate": "0.0001",
            },
            {
                "symbol": "ETHUSDT",
                "markPrice": "3200",
                "indexPrice": "3198",
                "lastFundingRate": "-0.00005",
                "nextFundingTime": "1786104000000",
                "interestRate": "0.0001",
            },
            {"symbol": "OTHERUSDT"},
        ]

    async def get_funding_info(self):
        self.funding_info_calls += 1
        return [
            {"symbol": "BTCUSDT", "fundingIntervalHours": 8},
            {"symbol": "ETHUSDT", "fundingIntervalHours": 4},
        ]


class FakeEventRepo:
    def __init__(self, latest: FundingEvent | None = None) -> None:
        self.latest = latest
        self.upserted: tuple[FundingEvent, ...] = ()

    async def latest_event(self, symbol_id: int) -> FundingEvent | None:
        return self.latest

    async def upsert_events(self, events: tuple[FundingEvent, ...]) -> tuple[int, int]:
        self.upserted = events
        return len(events), 0

    async def list_events(self, *args: object, **kwargs: object) -> tuple[FundingEvent, ...]:
        return self.upserted


class FakeCurrentRepo:
    def __init__(self) -> None:
        self.items: tuple[FundingCurrent, ...] = ()

    async def upsert_many(self, items: tuple[FundingCurrent, ...]) -> int:
        self.items = items
        return len(items)

    async def get(self, symbol_id: int) -> None:
        return None


class FakeSyncRepo:
    def __init__(self) -> None:
        self.success: tuple[object, ...] | None = None
        self.errors: list[tuple[int, str]] = []

    async def mark_history_success(self, symbol_id: int, **kwargs: object) -> None:
        self.success = (symbol_id, kwargs)

    async def mark_error(self, symbol_id: int, error: str) -> None:
        self.errors.append((symbol_id, error))


class FakeAnalytics:
    async def recalculate_symbol(
        self,
        symbol: FundingSymbol,
        *,
        now: datetime | None = None,
    ) -> int:
        return 3


def payload_event(symbol: str, funding_time: datetime, rate: str = "0.0001") -> dict[str, object]:
    return {
        "symbol": symbol,
        "fundingRate": rate,
        "fundingTime": int(funding_time.timestamp() * 1000),
        "markPrice": "65000",
    }


def test_parse_history_payload_uses_fraction_units_and_utc_time() -> None:
    parsed = parse_funding_history_event(BTC, payload_event("BTCUSDT", NOW))

    assert parsed.funding_rate == Decimal("0.0001")
    assert parsed.funding_time.tzinfo == UTC


def test_parse_history_payload_rejects_unknown_symbol() -> None:
    with pytest.raises(BinanceUnavailableError, match="ETHUSDT"):
        parse_funding_history_event(BTC, payload_event("ETHUSDT", NOW))


def test_parse_current_payload() -> None:
    current = parse_funding_current(
        BTC,
        {
            "symbol": "BTCUSDT",
            "markPrice": "65000",
            "indexPrice": "64990",
            "lastFundingRate": "0.0001",
            "nextFundingTime": "1786104000000",
            "interestRate": "0.0001",
        },
        funding_interval_hours=Decimal("8"),
    )

    assert current.last_funding_rate == Decimal("0.0001")
    assert current.funding_interval_hours == Decimal("8")


@pytest.mark.asyncio
async def test_history_pagination_advances_with_start_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(funding_service, "BINANCE_FUNDING_LIMIT", 2)
    first = [
        payload_event("BTCUSDT", NOW - timedelta(hours=16)),
        payload_event("BTCUSDT", NOW - timedelta(hours=8)),
    ]
    second = [payload_event("BTCUSDT", NOW)]
    client = FakeFundingClient([first, second])
    event_repo = FakeEventRepo()
    service = FundingHistoryService(
        client,  # type: ignore[arg-type]
        event_repo,  # type: ignore[arg-type]
        FakeSyncRepo(),  # type: ignore[arg-type]
        FakeAnalytics(),  # type: ignore[arg-type]
    )

    outcome = await service.sync_symbol(BTC, days=30, now=NOW)

    assert outcome.pages_requested == 2
    assert outcome.events_received == 3
    assert len(event_repo.upserted) == 3
    assert client.history_calls[1]["start"] > client.history_calls[0]["start"]


@pytest.mark.asyncio
async def test_incremental_sync_uses_overlap_from_latest_event() -> None:
    latest = FundingEvent(1, "BTCUSDT", NOW - timedelta(hours=8), Decimal("0.0001"))
    client = FakeFundingClient([[payload_event("BTCUSDT", NOW)]])
    service = FundingHistoryService(
        client,  # type: ignore[arg-type]
        FakeEventRepo(latest),  # type: ignore[arg-type]
        FakeSyncRepo(),  # type: ignore[arg-type]
        FakeAnalytics(),  # type: ignore[arg-type]
    )

    await service.sync_symbol(BTC, days=30, now=NOW)

    expected_start = int((latest.funding_time - timedelta(hours=12)).timestamp() * 1000)
    assert client.history_calls[0]["start"] == expected_start


@pytest.mark.asyncio
async def test_current_sync_uses_batch_premium_index() -> None:
    client = FakeFundingClient()
    repo = FakeCurrentRepo()
    service = FundingCurrentService(client, repo)  # type: ignore[arg-type]

    updated = await service.sync_current([BTC, ETH])

    assert updated == 2
    assert client.premium_calls == 1
    assert client.funding_info_calls == 1
    assert repo.items[0].funding_interval_hours == Decimal("8")
    assert repo.items[1].funding_interval_hours == Decimal("4")
