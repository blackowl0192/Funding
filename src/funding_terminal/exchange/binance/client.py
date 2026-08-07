from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any, cast

import httpx

from funding_terminal.config import Settings
from funding_terminal.domain.errors import BinanceUnavailableError
from funding_terminal.domain.models import ExchangeMetadata
from funding_terminal.exchange.binance.parser import parse_exchange_metadata

logger = logging.getLogger(__name__)
type QueryParams = Mapping[str, str | int | float | bool | None]


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

    async def get_funding_rate_history(
        self,
        symbol: str,
        *,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> Sequence[Mapping[str, object]]:
        return await self._get_json_list(
            self._settings.binance_futures_base_url,
            "/fapi/v1/fundingRate",
            f"{symbol} fundingRate",
            params={
                "symbol": symbol,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "limit": limit,
            },
        )

    async def get_premium_index(
        self,
        symbol: str | None = None,
    ) -> Sequence[Mapping[str, object]]:
        params = {"symbol": symbol} if symbol else None
        payload = await self._get_json_any(
            self._settings.binance_futures_base_url,
            "/fapi/v1/premiumIndex",
            "premiumIndex",
            params=params,
        )
        if isinstance(payload, list):
            return cast(Sequence[Mapping[str, object]], payload)
        if isinstance(payload, dict):
            return (cast(Mapping[str, object], payload),)
        raise BinanceUnavailableError("Binance premiumIndex returned invalid JSON.")

    async def get_funding_info(self) -> Sequence[Mapping[str, object]]:
        return await self._get_json_list(
            self._settings.binance_futures_base_url,
            "/fapi/v1/fundingInfo",
            "fundingInfo",
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
        params: QueryParams | None = None,
        attempts: int = 3,
    ) -> Mapping[str, object]:
        payload = await self._get_json_any(
            base_url,
            path,
            label,
            params=params,
            attempts=attempts,
        )
        if not isinstance(payload, dict):
            raise BinanceUnavailableError(f"Binance {label} returned non-object JSON.")
        return cast(Mapping[str, object], payload)

    async def _get_json_list(
        self,
        base_url: str,
        path: str,
        label: str,
        *,
        params: QueryParams | None = None,
        attempts: int = 3,
    ) -> Sequence[Mapping[str, object]]:
        payload = await self._get_json_any(
            base_url,
            path,
            label,
            params=params,
            attempts=attempts,
        )
        if not isinstance(payload, list):
            raise BinanceUnavailableError(f"Binance {label} returned non-list JSON.")
        return cast(Sequence[Mapping[str, object]], payload)

    async def _get_json_any(
        self,
        base_url: str,
        path: str,
        label: str,
        *,
        params: QueryParams | None = None,
        attempts: int = 3,
    ) -> Any:
        url = f"{base_url.rstrip('/')}{path}"
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = await self._request(url, params=params)
                if response.status_code == 429:
                    logger.warning("Binance %s rate limited on attempt %s", label, attempt)
                    if attempt < attempts:
                        await asyncio.sleep(_retry_delay_seconds(response, attempt))
                        continue
                if response.status_code >= 500 and attempt < attempts:
                    logger.warning(
                        "Binance %s server error %s on attempt %s",
                        label,
                        response.status_code,
                        attempt,
                    )
                    await asyncio.sleep(_retry_delay_seconds(response, attempt))
                    continue
                response.raise_for_status()
                payload = response.json()
                return payload
            except (ValueError, httpx.HTTPError, BinanceUnavailableError) as exc:
                last_error = exc
                logger.warning("Binance %s request failed on attempt %s: %s", label, attempt, exc)
                if attempt < attempts:
                    await asyncio.sleep(0.25 * (2 ** (attempt - 1)))

        raise BinanceUnavailableError(f"Binance {label} is unavailable.") from last_error

    async def _request(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, params=params)

        timeout = httpx.Timeout(self._settings.binance_http_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.get(url, params=params)


def _retry_delay_seconds(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 5.0)
        except ValueError:
            pass
    return 0.25 * (2 ** (attempt - 1))
