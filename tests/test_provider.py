from datetime import date
from decimal import Decimal

import httpx
import pytest

from financial_hub.exceptions import ProviderError, RateLimitError
from financial_hub.providers.finmind import FinMindProvider


def test_finmind_parses_latest_positive_quote():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": 200,
                "data": [
                    {"date": "2025-01-02", "close": 10},
                    {"date": "2025-01-03", "close": 11.5},
                ],
            },
        )

    provider = FinMindProvider("secret", transport=httpx.MockTransport(handler))
    quote = provider.latest_quote("2330", date(2025, 1, 1))
    assert quote.close == Decimal("11.50")
    assert type(quote.close) is Decimal
    assert quote.market_date == date(2025, 1, 3)


def test_provider_redacts_token_and_normalizes_rate_limit():
    token = "do-not-leak"

    def failed(request):
        raise httpx.ConnectError(f"bad token {token}", request=request)

    with pytest.raises(ProviderError) as caught:
        FinMindProvider(token, transport=httpx.MockTransport(failed)).security_master()
    assert token not in str(caught.value)
    provider = FinMindProvider(
        token, transport=httpx.MockTransport(lambda request: httpx.Response(429))
    )
    with pytest.raises(RateLimitError):
        provider.security_master()
