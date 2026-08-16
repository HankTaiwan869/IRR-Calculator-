from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..exceptions import ValidationError
from ..models import Transaction, TransactionAudit, TransactionKind

ZERO = 0


@dataclass(frozen=True, slots=True)
class TransactionInput:
    portfolio_id: int
    security_id: int | None
    kind: TransactionKind | str
    trade_date: date
    shares_delta: int = ZERO
    amount: int = ZERO
    source_key: str | None = None


def _integer(value: Decimal | str | float, field: str) -> int:
    try:
        number = Decimal(str(value))
    except Exception as error:
        raise ValidationError(f"{field} must be an integer.") from error
    if not number.is_finite() or number != number.to_integral_value():
        raise ValidationError(f"{field} must be an integer.")
    return int(number)


def normalized(data: TransactionInput) -> TransactionInput:
    try:
        kind = TransactionKind(data.kind)
    except ValueError as error:
        raise ValidationError(f"Unknown transaction kind: {data.kind}") from error
    return TransactionInput(
        portfolio_id=data.portfolio_id,
        security_id=data.security_id,
        kind=kind,
        trade_date=data.trade_date,
        shares_delta=_integer(data.shares_delta, "Shares"),
        amount=_integer(data.amount, "Amount"),
        source_key=data.source_key,
    )


def validate(data: TransactionInput) -> TransactionInput:
    data = normalized(data)
    kind = TransactionKind(data.kind)
    if kind is not TransactionKind.LEGACY_CASH_FLOW and data.security_id is None:
        raise ValidationError("A security is required for this transaction.")
    if kind is TransactionKind.BUY:
        if data.shares_delta <= ZERO or data.amount >= ZERO:
            raise ValidationError(
                "A buy requires positive shares and a negative amount."
            )
    elif kind is TransactionKind.SELL:
        if data.shares_delta >= ZERO or data.amount <= ZERO:
            raise ValidationError(
                "A sell requires negative shares and a positive amount."
            )
    elif kind is TransactionKind.DIVIDEND:
        if data.shares_delta != ZERO or data.amount <= ZERO:
            raise ValidationError(
                "A paid-out dividend requires zero shares and a positive amount."
            )
    elif kind is TransactionKind.REINVESTED_DIVIDEND:
        if data.shares_delta <= ZERO or data.amount != ZERO:
            raise ValidationError(
                "A reinvested dividend requires positive shares and a zero amount."
            )
    elif kind is TransactionKind.OPENING_POSITION:
        if data.shares_delta <= ZERO or data.amount >= ZERO:
            raise ValidationError(
                "An opening position requires positive shares and a negative amount."
            )
    elif kind is TransactionKind.LEGACY_CASH_FLOW:
        if data.shares_delta != ZERO:
            raise ValidationError("A legacy cash flow cannot contain shares.")
        if data.amount == ZERO:
            raise ValidationError("A legacy cash flow cannot be zero.")
    return data


def snapshot(transaction: Transaction) -> dict[str, Any]:
    fields = (
        "portfolio_id",
        "security_id",
        "kind",
        "trade_date",
        "shares_delta",
        "amount",
        "source_key",
        "deleted_at",
    )
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(transaction, field)
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        result[field] = value
    return result


def _apply(transaction: Transaction, data: TransactionInput) -> None:
    for key, value in asdict(data).items():
        if key == "kind":
            value = TransactionKind(value).value
        setattr(transaction, key, value)


def _assert_nonnegative_ledger(
    session: Session, portfolio_id: int, security_id: int | None
) -> None:
    if security_id is None:
        return
    rows = session.scalars(
        select(Transaction)
        .where(
            Transaction.portfolio_id == portfolio_id,
            Transaction.security_id == security_id,
            Transaction.deleted_at.is_(None),
        )
        .order_by(Transaction.trade_date, Transaction.id)
    )
    shares = ZERO
    for row in rows:
        shares += row.shares_delta
        if shares < ZERO:
            raise ValidationError(
                f"Transaction {row.id} would make holdings negative on {row.trade_date}."
            )


def create_transaction(session: Session, data: TransactionInput) -> Transaction:
    data = validate(data)
    transaction = Transaction()
    _apply(transaction, data)
    session.add(transaction)
    session.flush()
    _assert_nonnegative_ledger(session, data.portfolio_id, data.security_id)
    return transaction


def edit_transaction(
    session: Session, transaction_id: int, data: TransactionInput
) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise ValidationError("Transaction not found.")
    data = validate(data)
    before = snapshot(transaction)
    old_scope = (transaction.portfolio_id, transaction.security_id)
    _apply(transaction, data)
    session.flush()
    _assert_nonnegative_ledger(session, *old_scope)
    _assert_nonnegative_ledger(session, data.portfolio_id, data.security_id)
    session.add(
        TransactionAudit(
            transaction_id=transaction.id,
            action="EDIT",
            before=before,
            after=snapshot(transaction),
        )
    )
    return transaction


def delete_transaction(session: Session, transaction_id: int) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise ValidationError("Transaction not found.")
    scope = (transaction.portfolio_id, transaction.security_id)
    session.execute(
        delete(TransactionAudit).where(
            TransactionAudit.transaction_id == transaction_id
        )
    )
    session.delete(transaction)
    session.flush()
    _assert_nonnegative_ledger(session, *scope)
    return transaction

