from datetime import date
from decimal import Decimal

from irr_calculator.models import Quote, Transaction, TransactionKind
from irr_calculator.services.analytics import calculate_xirr, portfolio_summary
from irr_calculator.services.ledger import replay_ledger
from irr_calculator.services.transactions import TransactionInput, create_transaction

D = Decimal


def test_reinvested_dividend_increases_shares_basis_and_income_without_xirr_flow(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(session, TransactionInput(portfolio_id, security_id, TransactionKind.BUY, date(2024, 1, 1), D("10"), D("-100"), D("100")))
        reinvested = create_transaction(session, TransactionInput(portfolio_id, security_id, TransactionKind.REINVESTED_DIVIDEND, date(2024, 7, 1), D("1"), D("0"), D("10"), D("10")))
        assert reinvested.external_cash_flow == 0
        session.add(Quote(security_id=security_id, market_date=date(2025, 1, 1), refresh_cycle_date=date(2025, 1, 1), close=D("120") / D("11")))
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)
        ledger = replay_ledger(list(session.query(Transaction).all()))
    assert ledger.shares == D("11")
    assert ledger.cost_basis == D("110")
    assert ledger.dividend_income == D("10")
    assert summary.total_assets.quantize(D("0.01")) == D("120.00")
    assert summary.total_profit.quantize(D("0.01")) == D("20.00")
    assert summary.annual_irr is not None
    assert summary.annual_irr > 0.19


def test_closed_position_keeps_realized_profit_and_dividends(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(session, TransactionInput(portfolio_id, security_id, TransactionKind.BUY, date(2024, 1, 1), D("10"), D("-100"), D("100")))
        create_transaction(session, TransactionInput(portfolio_id, security_id, TransactionKind.DIVIDEND, date(2024, 6, 1), D("0"), D("5"), income_amount=D("5")))
        create_transaction(session, TransactionInput(portfolio_id, security_id, TransactionKind.SELL, date(2024, 12, 1), D("-10"), D("130"), D("130")))
    with factory() as session:
        summary = portfolio_summary(session, date(2025, 1, 1), portfolio_id)
    assert summary.total_assets == 0
    assert summary.realized_profit == D("30")
    assert summary.dividend_income == D("5")
    assert summary.total_profit == D("35")


def test_xirr_not_calculable_without_sign_change():
    row = Transaction(kind=TransactionKind.LEGACY_CASH_FLOW, trade_date=date(2024, 1, 1), external_cash_flow=D("5"), shares_delta=0, trade_amount=0, income_amount=0, fees=0, portfolio_id=1)
    assert calculate_xirr([row], D("5"), date(2025, 1, 1)) is None
