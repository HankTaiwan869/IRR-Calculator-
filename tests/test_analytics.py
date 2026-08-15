from datetime import date

from irr_calculator.models import Portfolio, Quote, Transaction, TransactionKind
from irr_calculator.services.analytics import (
    calculate_xirr,
    portfolio_summary,
    projection,
)
from irr_calculator.services.ledger import replay_ledger
from irr_calculator.services.transactions import TransactionInput, create_transaction


def test_reinvested_dividend_increases_shares_basis_and_income_without_xirr_flow(db):
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
                100,
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
                10,
                10,
            ),
        )
        assert reinvested.external_cash_flow == 0
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
        ledger = replay_ledger(list(session.query(Transaction).all()))
    assert ledger.shares == 11
    assert ledger.cost_basis == 110
    assert ledger.dividend_income == 10
    assert summary.total_assets == 121
    assert summary.total_profit == 21
    assert summary.annual_irr is not None
    assert summary.annual_irr > 0.19


def test_closed_position_keeps_realized_profit_and_dividends(db):
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
                100,
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
                income_amount=5,
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
                130,
            ),
        )
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)
    assert summary.total_assets == 0
    assert summary.realized_profit == 30
    assert summary.dividend_income == 5
    assert summary.total_profit == 35


def test_moving_average_cost_uses_integer_half_up_allocation(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2024, 1, 1),
                3,
                -100,
                100,
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.SELL,
                date(2024, 2, 1),
                -1,
                50,
                50,
            ),
        )
    with factory() as session:
        ledger = replay_ledger(list(session.query(Transaction).all()))
    assert ledger.shares == 2
    assert ledger.cost_basis == 67
    assert ledger.average_cost == 34
    assert ledger.realized_profit == 17


def test_ledger_and_projection_outputs_are_integers_with_half_up_rounding(db):
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
                1,
            ),
        )
    with factory() as session:
        ledger = replay_ledger(list(session.query(Transaction).all()))

    assert ledger.average_cost == 1
    assert all(
        type(value) is int
        for value in (
            ledger.shares,
            ledger.cost_basis,
            ledger.average_cost,
            ledger.realized_profit,
            ledger.dividend_income,
        )
    )
    values = projection(1, years=1, rates=(0.5,))
    assert values == ((1, 2),)
    assert all(type(value) is int for row in values for value in row)


def test_xirr_not_calculable_without_sign_change():
    row = Transaction(
        kind=TransactionKind.LEGACY_CASH_FLOW,
        trade_date=date(2024, 1, 1),
        external_cash_flow=5,
        shares_delta=0,
        trade_amount=0,
        income_amount=0,
        portfolio_id=1,
    )
    assert calculate_xirr([row], 5, date(2025, 1, 1)) is None


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
                100,
            ),
        )
        create_transaction(
            session,
            TransactionInput(
                second.id,
                security_id,
                TransactionKind.BUY,
                date(2024, 2, 1),
                10,
                -200,
                200,
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
    position = summary.positions[0]
    assert position.shares == 15
    assert position.cost_basis == 250
    assert position.realized_profit == 25
    assert position.market_value == 300
    assert summary.realized_profit == 25
    assert summary.unrealized_profit == 50


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
                100,
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
                1000,
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
    assert summary.annual_irr is not None
    assert abs(summary.annual_irr - 0.1) < 0.001


def test_missing_open_position_quote_makes_total_assets_and_projection_unavailable(db):
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
                100,
            ),
        )

    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)

    assert summary.total_assets is None
    assert summary.unrealized_profit is None
    assert summary.total_profit is None
    assert summary.annual_irr is None
    assert projection(summary.total_assets) is None


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
                100,
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
                900,
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
