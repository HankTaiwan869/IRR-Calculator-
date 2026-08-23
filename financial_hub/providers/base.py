from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SecurityInfo:
    symbol: str
    name_zh: str
    exchange: str
    security_type: str


@dataclass(frozen=True, slots=True)
class DailyQuote:
    symbol: str
    market_date: date
    close: Decimal


class SecuritiesProvider(Protocol):
    @property
    def name(self) -> str: ...
    def security_master(self) -> Sequence[SecurityInfo]: ...
    def latest_quote(self, symbol: str, start_date: date) -> DailyQuote: ...
