from __future__ import annotations

import httpx
import pytest

from funding_terminal.config import Settings
from funding_terminal.domain.errors import BinanceUnavailableError
from funding_terminal.exchange.binance.client import BinancePublicClient


class FakeHttpClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, object]] = []

    async def get(self, url: str, params=None):  # noqa: ANN001
        self.calls.append((url, params))
        return self.responses.pop(0)

    async def aclose(self) -> None:
        return None


def response(
    status_code: int,
    payload: object,
    *,
    retry_after: str | None = None,
) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after else None
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request("GET", "https://fapi.binance.com/test"),
    )


@pytest.mark.asyncio
async def test_funding_history_endpoint_passes_pagination_params() -> None:
    fake = FakeHttpClient([response(200, [{"symbol": "BTCUSDT"}])])
    client = BinancePublicClient(Settings(database_url="postgresql://example"), fake)  # type: ignore[arg-type]

    payload = await client.get_funding_rate_history(
        "BTCUSDT",
        start_time_ms=1,
        end_time_ms=2,
        limit=1000,
    )

    assert payload[0]["symbol"] == "BTCUSDT"
    assert fake.calls[0][0].endswith("/fapi/v1/fundingRate")
    assert fake.calls[0][1] == {
        "symbol": "BTCUSDT",
        "startTime": 1,
        "endTime": 2,
        "limit": 1000,
    }


@pytest.mark.asyncio
async def test_premium_index_normalizes_single_object_response() -> None:
    fake = FakeHttpClient([response(200, {"symbol": "BTCUSDT"})])
    client = BinancePublicClient(Settings(database_url="postgresql://example"), fake)  # type: ignore[arg-type]

    payload = await client.get_premium_index("BTCUSDT")

    assert len(payload) == 1
    assert payload[0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_429_retries_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("funding_terminal.exchange.binance.client.asyncio.sleep", fake_sleep)
    fake = FakeHttpClient(
        [
            response(429, {"code": -1003}, retry_after="0"),
            response(200, [{"symbol": "BTCUSDT"}]),
        ]
    )
    client = BinancePublicClient(Settings(database_url="postgresql://example"), fake)  # type: ignore[arg-type]

    payload = await client.get_funding_info()

    assert payload[0]["symbol"] == "BTCUSDT"
    assert len(fake.calls) == 2
    assert sleeps == [0.0]


@pytest.mark.asyncio
async def test_malformed_list_payload_raises() -> None:
    fake = FakeHttpClient([response(200, {"symbol": "BTCUSDT"})])
    client = BinancePublicClient(Settings(database_url="postgresql://example"), fake)  # type: ignore[arg-type]

    with pytest.raises(BinanceUnavailableError, match="non-list"):
        await client.get_funding_info()
