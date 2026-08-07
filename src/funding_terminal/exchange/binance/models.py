from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BinanceEndpoint:
    label: str
    base_url: str
    path: str

    @property
    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}{self.path}"

