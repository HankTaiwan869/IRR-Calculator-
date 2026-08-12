from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from irr_calculator.exceptions import ValidationError
from irr_calculator.models import Transaction, TransactionAudit, TransactionKind
from irr_calculator.services.transactions import TransactionInput, create_transaction, delete_transaction, edit_transaction, restore_transaction

D = Decimal


def buy(portfolio_id, security_id, day=date(2025, 1, 1), shares="10", amount="100"):
    return TransactionInput(portfolio_id, security_id, TransactionKind.BUY, day, D(shares), -D(amount), D(amount))


def test_signed_rules_and_backdated_negative_holdings(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(session, buy(portfolio_id, security_id))
        create_transaction(session, TransactionInput(portfolio_id, security_id, TransactionKind.SELL, date(2025, 2, 1), D("-5"), D("60"), D("60")))
    with pytest.raises(ValidationError), factory.begin() as session:
        create_transaction(session, TransactionInput(portfolio_id, security_id, TransactionKind.SELL, date(2024, 12, 1), D("-1"), D("12"), D("12")))


def test_edit_delete_restore_are_audited(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        transaction = create_transaction(session, buy(portfolio_id, security_id))
        transaction_id = transaction.id
    with factory.begin() as session:
        edit_transaction(session, transaction_id, buy(portfolio_id, security_id, amount="110"))
    with factory.begin() as session:
        delete_transaction(session, transaction_id)
    with factory.begin() as session:
        restore_transaction(session, transaction_id)
    with factory() as session:
        assert [item.action for item in session.scalars(select(TransactionAudit).order_by(TransactionAudit.id))] == ["EDIT", "DELETE", "RESTORE"]
        assert session.get(Transaction, transaction_id).deleted_at is None


def test_reinvestment_requires_explicit_residual(db):
    _engine, factory, (portfolio_id, security_id) = db
    with pytest.raises(ValidationError):
        with factory.begin() as session:
            create_transaction(session, TransactionInput(
                portfolio_id, security_id, TransactionKind.REINVESTED_DIVIDEND,
                date(2025, 2, 1), D("1"), D("0"), D("9"), D("10"), fees=D("0.5"),
            ))
