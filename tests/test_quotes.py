from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from financial_hub.models import Portfolio, Quote, Security, TransactionKind
from financial_hub.providers.base import DailyQuote
from financial_hub.services.quotes import refresh_prices
from financial_hub.services.transactions import TransactionInput, create_transaction


class FakeProvider:
    name = "FinMind"

    def __init__(
        self,
        market_date=date(2025, 1, 3),
        close=Decimal("100.00"),
    ):
        self.calls = 0
        self.fail = False
        self.market_date = market_date
        self.close = close

    def latest_quote(self, symbol, start_date):
        self.calls += 1
        if self.fail:
            raise RuntimeError("temporary provider failure")
        return DailyQuote(symbol, self.market_date, self.close)


class FractionalProvider(FakeProvider):
    def latest_quote(self, symbol, start_date):
        self.calls += 1
        return DailyQuote(symbol, date(2025, 1, 3), Decimal("100.505"))


def test_repeated_same_day_refresh_reaches_provider_and_failure_keeps_quote(db):
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
            ),
        )
    provider = FakeProvider()
    cycle = date(2025, 1, 5)  # Sunday; latest market close is Friday.
    first = refresh_prices(factory, provider, cycle)
    second = refresh_prices(factory, provider, cycle)
    assert first.refreshed == ("2330",)
    assert second.refreshed == ("2330",)
    assert first.failed == ()
    assert second.failed == ()
    assert provider.calls == 2

    provider.fail = True
    failed = refresh_prices(factory, provider, date(2025, 1, 6))
    assert failed.failed[0][0] == "2330"
    assert provider.calls == 3
    with factory() as session:
        quote = session.scalar(select(Quote))
        assert quote.close == Decimal("100.00")
        assert type(quote.close) is Decimal


def test_same_market_date_refresh_updates_one_quote_and_fetched_at(db):
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
            ),
        )
        old_fetched_at = datetime(2024, 1, 1)  # noqa: DTZ001 - SQLite returns naive timestamps
        old_quote = Quote(
            security_id=security_id,
            market_date=date(2025, 1, 3),
            refresh_cycle_date=date(2025, 1, 4),
            close=Decimal("100.00"),
            fetched_at=old_fetched_at,
        )
        session.add(old_quote)
        session.flush()
        old_quote_id = old_quote.id

    provider = FakeProvider(close=Decimal("101.25"))
    result = refresh_prices(factory, provider, date(2025, 1, 5))

    assert result.refreshed == ("2330",)
    assert result.failed == ()
    with factory() as session:
        quotes = list(session.scalars(select(Quote)))
    assert len(quotes) == 1
    quote = quotes[0]
    assert quote.id == old_quote_id
    assert quote.market_date == date(2025, 1, 3)
    assert quote.close == Decimal("101.25")
    assert quote.fetched_at > old_fetched_at


def test_new_market_date_preserves_previous_quote_row(db):
    _engine, factory, (portfolio_id, security_id) = db
    old_market_date = date(2025, 1, 2)
    old_refresh_cycle_date = date(2025, 1, 2)
    old_fetched_at = datetime(2024, 1, 1)  # noqa: DTZ001 - SQLite returns naive timestamps
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
            ),
        )
        old_quote = Quote(
            security_id=security_id,
            market_date=old_market_date,
            refresh_cycle_date=old_refresh_cycle_date,
            close=Decimal("99.00"),
            fetched_at=old_fetched_at,
        )
        session.add(old_quote)
        session.flush()
        old_quote_id = old_quote.id

    provider = FakeProvider(
        market_date=date(2025, 1, 3),
        close=Decimal("100.00"),
    )
    cycle_date = date(2025, 1, 5)
    result = refresh_prices(factory, provider, cycle_date)

    assert result.refreshed == ("2330",)
    assert result.failed == ()
    with factory() as session:
        quotes = list(session.scalars(select(Quote)))
    assert len(quotes) == 2
    previous = next(quote for quote in quotes if quote.market_date == old_market_date)
    current = next(
        quote for quote in quotes if quote.market_date == date(2025, 1, 3)
    )
    assert previous.id == old_quote_id
    assert previous.close == Decimal("99.00")
    assert previous.refresh_cycle_date == old_refresh_cycle_date
    assert previous.fetched_at == old_fetched_at
    assert current.close == Decimal("100.00")
    assert current.refresh_cycle_date == cycle_date


def test_failed_same_day_refresh_preserves_quote_and_allows_retry(db):
    _engine, factory, (portfolio_id, security_id) = db
    cycle_date = date(2025, 1, 5)
    market_date = date(2025, 1, 3)
    old_fetched_at = datetime(2024, 1, 1)  # noqa: DTZ001 - SQLite returns naive timestamps
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
            ),
        )
        session.add(
            Quote(
                security_id=security_id,
                market_date=market_date,
                refresh_cycle_date=cycle_date,
                close=Decimal("100.00"),
                fetched_at=old_fetched_at,
            )
        )

    provider = FakeProvider(market_date=market_date, close=Decimal("101.00"))
    provider.fail = True
    failed = refresh_prices(factory, provider, cycle_date)

    assert failed.refreshed == ()
    assert failed.failed == (("2330", "temporary provider failure"),)
    assert provider.calls == 1
    with factory() as session:
        quote = session.scalar(select(Quote))
        assert quote.market_date == market_date
        assert quote.refresh_cycle_date == cycle_date
        assert quote.close == Decimal("100.00")
        assert quote.fetched_at == old_fetched_at

    provider.fail = False
    retried = refresh_prices(factory, provider, cycle_date)

    assert retried.refreshed == ("2330",)
    assert retried.failed == ()
    assert provider.calls == 2
    with factory() as session:
        quote = session.scalar(select(Quote))
        assert quote.market_date == market_date
        assert quote.close == Decimal("101.00")
        assert quote.fetched_at > old_fetched_at


def test_refresh_normalizes_provider_close_to_two_decimal_places(db):
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
            ),
        )

    result = refresh_prices(factory, FractionalProvider(), date(2025, 1, 5))

    assert result.refreshed == ("2330",)
    with factory() as session:
        close = session.scalar(select(Quote.close))
    assert close == Decimal("100.51")
    assert type(close) is Decimal


def test_all_portfolios_refresh_excludes_archived_but_explicit_refresh_includes_it(db):
    _engine, factory, (active_portfolio_id, active_security_id) = db
    with factory.begin() as session:
        archived = Portfolio(name="Archived", archived_at=date(2025, 1, 1))
        archived_security = Security(
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
            ),
        )

    provider = FakeProvider()
    combined = refresh_prices(factory, provider, date(2025, 1, 5))
    archived_only = refresh_prices(factory, provider, date(2025, 1, 6), archived.id)

    assert combined.refreshed == ("2330",)
    assert archived_only.refreshed == ("0050",)
