from datetime import date

import pytest

from financial_hub.exceptions import ValidationError
from financial_hub.models import Transaction, TransactionKind
from financial_hub.services.transactions import (
    TransactionInput,
    create_transaction,
    delete_transaction,
    edit_transaction,
)


def buy(portfolio_id, security_id, day=date(2025, 1, 1), shares=10, amount=100):
    return TransactionInput(
        portfolio_id, security_id, TransactionKind.BUY, day, shares, -amount
    )


def test_signed_rules_and_backdated_negative_holdings(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        create_transaction(session, buy(portfolio_id, security_id))
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.SELL,
                date(2025, 2, 1),
                -5,
                60,
            ),
        )
    with pytest.raises(ValidationError), factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.SELL,
                date(2024, 12, 1),
                -1,
                12,
            ),
        )


@pytest.mark.parametrize(
    ("kind", "shares", "amount"),
    (
        (TransactionKind.BUY, 1, 0),
        (TransactionKind.SELL, -1, 0),
        (TransactionKind.DIVIDEND, 1, 10),
        (TransactionKind.REINVESTED_DIVIDEND, 1, 10),
        (TransactionKind.OPENING_POSITION, 1, 0),
        (TransactionKind.LEGACY_CASH_FLOW, 1, 10),
    ),
)
def test_activity_amount_and_share_rules_are_enforced(db, kind, shares, amount):
    _engine, factory, (portfolio_id, security_id) = db
    with pytest.raises(ValidationError), factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                kind,
                date(2025, 1, 1),
                shares,
                amount,
            ),
        )


def test_edit_updates_transaction_and_delete_is_permanent(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        transaction = create_transaction(session, buy(portfolio_id, security_id))
        transaction_id = transaction.id
    with factory.begin() as session:
        edit_transaction(
            session, transaction_id, buy(portfolio_id, security_id, amount=110)
        )
    with factory() as session:
        edited = session.get(Transaction, transaction_id)
        assert edited is not None
        assert edited.amount == -110
    with factory.begin() as session:
        delete_transaction(session, transaction_id)
    with factory() as session:
        assert session.get(Transaction, transaction_id) is None


def test_fractional_inputs_are_rejected(db):
    _engine, factory, (portfolio_id, security_id) = db
    with pytest.raises(ValidationError), factory.begin() as session:
        create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.REINVESTED_DIVIDEND,
                date(2025, 2, 1),
                1.5,
                0,
            ),
        )


def test_integer_like_inputs_are_normalized_to_builtin_ints(db):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        row = create_transaction(
            session,
            TransactionInput(
                portfolio_id,
                security_id,
                TransactionKind.BUY,
                date(2025, 1, 1),
                "2.0",
                "-100.0",
            ),
        )
        assert all(
            type(value) is int
            for value in (
                row.shares_delta,
                row.amount,
            )
        )
