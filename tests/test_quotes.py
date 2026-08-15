from datetime import date

from sqlalchemy import select

from irr_calculator.models import Portfolio, Quote, Security, TransactionKind
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
        return DailyQuote(symbol, date(2025, 1, 3), 100)


class FractionalProvider(FakeProvider):
    def latest_quote(self, symbol, start_date):
        self.calls += 1
        return DailyQuote(symbol, date(2025, 1, 3), 100.5)  # type: ignore[arg-type]


def test_daily_cycle_cache_works_when_market_date_is_older_and_failure_keeps_quote(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2025, 1, 1),
                1,
                -90,
                90,
            ),
        )
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
        assert quote.close == 100


def test_refresh_normalizes_provider_close_to_half_up_integer(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2025, 1, 1),
                1,
                -90,
                90,
            ),
        )

    result = refresh_prices(factory, FractionalProvider(), date(2025, 1, 5))

    assert result.refreshed == ("2330",)
    with factory() as session:
        close = session.scalar(select(Quote.close))
    assert close == 101
    assert type(close) is int


def test_all_portfolios_refresh_excludes_archived_but_explicit_refresh_includes_it(db):
    _engine, factory, (active_portfolio_id, active_security_id) = db
    with factory.begin() as session:
        archived = Portfolio(name="Archived", archived_at=date(2025, 1, 1))
        archived_security = Security(
            provider="FinMind",
            symbol="0050",
            name_zh="ETF",
            exchange="twse",
            security_type="etf",
        )
        session.add_all((archived, archived_security))
        session.flush()
        create_transaction(
            session,
            TransactionInput(
                active_portfolio_id,
                active_security_id,
                TransactionKind.BUY,
                date(2025, 1, 1),
                1,
                -90,
                90,
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                archived.id,
                archived_security.id,
                TransactionKind.BUY,
                date(2025, 1, 1),
                1,
                -50,
                50,
            ),
        )

    provider = FakeProvider()
    combined = refresh_prices(factory, provider, date(2025, 1, 5))
    archived_only = refresh_prices(factory, provider, date(2025, 1, 6), archived.id)

    assert combined.refreshed == ("2330",)
    assert archived_only.refreshed == ("0050",)
