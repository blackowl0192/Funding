from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import cast

import httpx

from funding_terminal.config import Settings
from funding_terminal.domain.errors import BinanceUnavailableError
from funding_terminal.domain.models import ExchangeMetadata
from funding_terminal.exchange.binance.parser import parse_exchange_metadata

logger = logging.getLogger(__name__)


class BinancePublicClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = http_client

    async def get_spot_exchange_info(self) -> Mapping[str, object]:
        return await self._get_json(
            self._settings.binance_spot_base_url,
            "/api/v3/exchangeInfo",
            "spot exchangeInfo",
        )

    async def get_futures_exchange_info(self) -> Mapping[str, object]:
        return await self._get_json(
            self._settings.binance_futures_base_url,
            "/fapi/v1/exchangeInfo",
            "futures exchangeInfo",
        )

    async def load_exchange_metadata(self) -> ExchangeMetadata:
        spot_payload, futures_payload = await asyncio.gather(
            self.get_spot_exchange_info(),
            self.get_futures_exchange_info(),
        )
        return parse_exchange_metadata(spot_payload, futures_payload)

    async def check_spot(self) -> bool:
        return await self._check(self._settings.binance_spot_base_url, "/api/v3/time", "spot time")

    async def check_futures(self) -> bool:
        return await self._check(
            self._settings.binance_futures_base_url,
            "/fapi/v1/time",
            "futures time",
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _check(self, base_url: str, path: str, label: str) -> bool:
        try:
            await self._get_json(base_url, path, label)
        except BinanceUnavailableError:
            return False
        return True

    async def _get_json(
        self,
        base_url: str,
        path: str,
        label: str,
        *,
        attempts: int = 3,
    ) -> Mapping[str, object]:
        url = f"{base_url.rstrip('/')}{path}"
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._request(url)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise BinanceUnavailableError(f"Binance {label} returned non-object JSON.")
                return cast(Mapping[str, object], payload)
            except (httpx.HTTPError, BinanceUnavailableError) as exc:
                last_error = exc
                logger.warning("Binance %s request failed on attempt %s: %s", label, attempt, exc)
                if attempt < attempts:
                    await asyncio.sleep(0.25 * (2 ** (attempt - 1)))

        raise BinanceUnavailableError(f"Binance {label} is unavailable.") from last_error

    async def _request(self, url: str) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url)

        timeout = httpx.Timeout(self._settings.binance_http_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(url)

