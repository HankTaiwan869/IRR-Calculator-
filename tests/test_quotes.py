from datetime import date
from decimal import Decimal

from sqlalchemy import select

from irr_calculator.models import Quote, TransactionKind
from irr_calculator.providers.base import DailyQuote
from irr_calculator.services.quotes import refresh_prices
from irr_calculator.services.transactions import TransactionInput, create_transaction


class FakeProvider:
    name = "FinMind"

    def __init__(self):
        self.calls = 0
        self.fail = False

    def latest_quote(self, symbol, start_date):
        self.calls += 1
        if self.fail:
            raise RuntimeError("temporary provider failure")
        return DailyQuote(symbol, date(2025, 1, 3), Decimal("100"))


def test_daily_cycle_cache_works_when_market_date_is_older_and_failure_keeps_quote(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(session, TransactionInput(
            portfolio_id, security_id, TransactionKind.BUY, date(2025, 1, 1),
            Decimal("1"), Decimal("-90"), Decimal("90"),
        ))
    provider = FakeProvider()
    cycle = date(2025, 1, 5)  # Sunday; latest market close is Friday.
    first = refresh_prices(factory, provider, cycle)
    second = refresh_prices(factory, provider, cycle)
    assert first.refreshed == ("2330",)
    assert second.cached == ("2330",)
    assert provider.calls == 1

    provider.fail = True
    failed = refresh_prices(factory, provider, date(2025, 1, 6))
    assert failed.failed[0][0] == "2330"
    with factory() as session:
        quote = session.scalar(select(Quote))
        assert quote.close == Decimal("100")
