from datetime import date
from decimal import Decimal

from financial_hub.models import Portfolio, Quote, Transaction, TransactionKind
from financial_hub.services.analytics import (
    calculate_xirr,
    portfolio_summary,
    projection,
)
from financial_hub.services.transactions import TransactionInput, create_transaction


def test_reinvested_dividend_updates_shares_but_not_cash_or_dividend_total(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                10,
                -100,
            ),
        )
        reinvested = create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.REINVESTED_DIVIDEND,
                date(2024, 7, 1),
                1,
                0,
            ),
        )
        assert reinvested.amount == 0
        session.add(
            Quote(
                security_id=security_id,
                market_date=date(2025, 1, 1),
                refresh_cycle_date=date(2025, 1, 1),
                close=11,
            )
        )
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)
    assert summary.positions[0].shares == 11
    assert summary.total_assets == 121
    assert summary.total_profit == 21
    assert summary.dividend_income == 0
    assert summary.annual_irr is not None and summary.annual_irr > 0.19


def test_paid_out_dividend_is_counted_once_in_profit_and_income(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                10,
                -100,
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.DIVIDEND,
                date(2024, 6, 1),
                0,
                5,
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.SELL,
                date(2024, 12, 1),
                -10,
                130,
            ),
        )
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)
    assert summary.total_assets == 0
    assert summary.dividend_income == 5
    assert summary.total_profit == 35


def test_decimal_quote_values_are_preserved_in_market_value_and_profit(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                2,
                -1,
            ),
        )
        session.add(
            Quote(
                security_id=security_id,
                market_date=date(2024, 1, 2),
                refresh_cycle_date=date(2024, 1, 2),
                close=Decimal("2.35"),
            )
        )
    with factory() as session:
        summary = portfolio_summary(session, date(2024, 1, 2), portfolio_id)
    assert summary.total_assets == Decimal("4.70")
    assert summary.total_profit == Decimal("3.70")
    assert type(summary.total_assets) is Decimal
    assert type(summary.total_profit) is Decimal


def test_xirr_not_calculable_without_sign_change():
    row = Transaction(
        kind=TransactionKind.LEGACY_CASH_FLOW,
        trade_date=date(2024, 1, 1),
        amount=5,
        shares_delta=0,
        portfolio_id=1,
    )
    assert calculate_xirr([row], 5, date(2025, 1, 1)) is None


def test_xirr_receives_fractional_terminal_value_at_library_boundary(monkeypatch):
    row = Transaction(
        kind=TransactionKind.BUY,
        trade_date=date(2024, 1, 1),
        amount=-100,
        shares_delta=1,
        portfolio_id=1,
    )
    seen = {}

    def fake_xirr(dates, values):
        seen["values"] = values
        return 0.1234

    monkeypatch.setattr("financial_hub.services.analytics.xirr", fake_xirr)
    assert calculate_xirr([row], Decimal("100.55"), date(2025, 1, 1)) == 0.1234
    assert seen["values"][-1] == 100.55


def test_all_portfolios_replays_separate_ledgers_before_aggregating(db):
    _engine, factory, (first_portfolio_id, security_id) = db
    with factory.begin() as session:
        second = Portfolio(name="Income")
        session.add(second)
        session.flush()
        create_transaction(
            session,
            TransactionInput(
                first_portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                10,
                -100,
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                second.id, security_id, TransactionKind.BUY, date(2024, 2, 1), 10, -200
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                first_portfolio_id,
                security_id,
                TransactionKind.SELL,
                date(2024, 6, 1),
                -5,
                75,
            ),
        )
        session.add(
            Quote(
                security_id=security_id,
                market_date=date(2025, 1, 1),
                refresh_cycle_date=date(2025, 1, 1),
                close=20,
            )
        )
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1))
    assert len(summary.positions) == 1
    assert summary.positions[0].shares == 15
    assert summary.total_assets == 300
    assert summary.total_profit == 75


def test_transactions_after_valuation_date_are_excluded_from_holdings_and_xirr(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                10,
                -100,
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2026, 1, 1),
                100,
                -1000,
            ),
        )
        session.add(
            Quote(
                security_id=security_id,
                market_date=date(2025, 1, 1),
                refresh_cycle_date=date(2025, 1, 1),
                close=11,
            )
        )
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)
    assert summary.positions[0].shares == 10
    assert summary.total_assets == 110
    assert summary.total_profit == 10
    assert summary.annual_irr is not None
    assert abs(summary.annual_irr - 0.1) < 0.001


def test_missing_quote_makes_total_assets_profit_and_xirr_unavailable(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                10,
                -100,
            ),
        )
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)
    assert summary.total_assets is None
    assert summary.total_profit is None
    assert summary.annual_irr is None
    assert projection(summary.total_assets) is None


def test_zero_value_legacy_opening_makes_profit_and_xirr_unavailable(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        session.add(
            Transaction(
                portfolio_id=portfolio_id,
                security_id=security_id,
                kind=TransactionKind.OPENING_POSITION.value,
                trade_date=date(2024, 1, 1),
                shares_delta=10,
                amount=0,
            )
        )
        session.add(
            Quote(
                security_id=security_id,
                market_date=date(2025, 1, 1),
                refresh_cycle_date=date(2025, 1, 1),
                close=11,
            )
        )
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)
    assert summary.total_assets == 110
    assert summary.total_profit is None
    assert summary.annual_irr is None


def test_all_portfolios_excludes_archived_but_explicit_selection_still_works(db):
    _engine, factory, (active_portfolio_id, security_id) = db
    with factory.begin() as session:
        archived = Portfolio(name="Archived", archived_at=date(2025, 1, 1))
        session.add(archived)
        session.flush()
        create_transaction(
            session,
            TransactionInput(
                active_portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                10,
                -100,
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                archived.id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                90,
                -900,
            ),
        )
        session.add(
            Quote(
                security_id=security_id,
                market_date=date(2025, 1, 1),
                refresh_cycle_date=date(2025, 1, 1),
                close=10,
            )
        )
    with factory() as session:
        combined = portfolio_summary(session, date(2025, 1, 1))
        archived_only = portfolio_summary(session, date(2025, 1, 1), archived.id)
    assert combined.positions[0].shares == 10
    assert combined.total_assets == 100
    assert archived_only.positions[0].shares == 90
    assert archived_only.total_assets == 900


def test_projection_preserves_decimal_calculations_until_display():
    values = projection(Decimal("1.25"), years=1, rates=(0.5,))
    assert values == ((Decimal("1.25"), Decimal("1.875")),)
    assert all(type(value) is Decimal for row in values for value in row)
