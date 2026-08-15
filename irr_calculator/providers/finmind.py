from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx

from ..exceptions import ProviderError, RateLimitError
from .base import DailyQuote, SecurityInfo


class FinMindProvider:
    BASE_URL = "https://api.finmindtrade.com/api/v4/data"

    def __init__(
        self,
        token: str,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token.strip()
        self._timeout = timeout
        self._transport = transport

    @property
    def name(self) -> str:
        return "FinMind"

    def _safe(self, message: object) -> str:
        text = str(message)
        return text.replace(self._token, "[REDACTED]") if self._token else text

    def _request(self, params: dict[str, str]) -> list[dict[str, Any]]:
        if self._token:
            params["token"] = self._token
        try:
            with httpx.Client(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = client.get(self.BASE_URL, params=params)
            if response.status_code == 429:
                raise RateLimitError("FinMind rate limit reached. Try again later.")
            response.raise_for_status()
            payload = response.json()
        except RateLimitError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise ProviderError(
                self._safe(f"FinMind request failed: {error}")
            ) from error
        if not isinstance(payload, dict) or payload.get("status") != 200:
            message = (
                payload.get("msg", "malformed response")
                if isinstance(payload, dict)
                else "malformed response"
            )
            if "limit" in str(message).lower():
                raise RateLimitError("FinMind rate limit reached. Try again later.")
            raise ProviderError(self._safe(f"FinMind error: {message}"))
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderError("FinMind returned malformed data.")
        return data

    def security_master(self) -> tuple[SecurityInfo, ...]:
        records = self._request({"dataset": "TaiwanStockInfo"})
        result: list[SecurityInfo] = []
        for item in records:
            symbol = str(item.get("stock_id", "")).strip()
            if not symbol:
                continue
            industry = str(item.get("industry_category", ""))
            result.append(
                SecurityInfo(
                    symbol=symbol,
                    name_zh=str(item.get("stock_name", "")).strip(),
                    exchange=str(item.get("type", item.get("exchange", ""))).strip(),
                    security_type="etf" if "ETF" in industry.upper() else "stock",
                )
            )
        return tuple(result)

    def latest_quote(self, symbol: str, start_date: date) -> DailyQuote:
        records = self._request(
            {
                "dataset": "TaiwanStockPrice",
                "data_id": symbol,
                "start_date": start_date.isoformat(),
            }
        )
        if not records:
            raise ProviderError(f"No daily price is available for {symbol}.")
        for item in reversed(records):
            try:
                raw_close = Decimal(str(item["close"]))
                close = int(raw_close.quantize(Decimal(1), rounding=ROUND_HALF_UP))
                market_date = date.fromisoformat(str(item["date"])[:10])
            except (KeyError, ValueError, InvalidOperation, TypeError) as error:
                raise ProviderError(
                    f"FinMind returned a malformed quote for {symbol}."
                ) from error
            if close > 0:
                return DailyQuote(symbol, market_date, close)
        raise ProviderError(f"FinMind returned no positive price for {symbol}.")
