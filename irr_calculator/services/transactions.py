from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
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
    external_cash_flow: int = ZERO
    trade_amount: int = ZERO
    income_amount: int = ZERO
    source_key: str | None = None


def _integer(value: Decimal | int | str | float, field: str) -> int:
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
        external_cash_flow=_integer(data.external_cash_flow, "External cash flow"),
        trade_amount=_integer(data.trade_amount, "Trade amount"),
        income_amount=_integer(data.income_amount, "Income amount"),
        source_key=data.source_key,
    )


def validate(data: TransactionInput) -> TransactionInput:
    data = normalized(data)
    kind = TransactionKind(data.kind)
    if data.trade_amount < ZERO or data.income_amount < ZERO:
        raise ValidationError("Trade amount and income cannot be negative.")
    if kind is not TransactionKind.LEGACY_CASH_FLOW and data.security_id is None:
        raise ValidationError("A security is required for this transaction.")
    if kind is TransactionKind.BUY:
        if data.shares_delta <= ZERO or data.external_cash_flow >= ZERO or data.trade_amount <= ZERO:
            raise ValidationError("A buy requires positive shares, negative external cash, and a trade amount.")
        if data.income_amount != ZERO:
            raise ValidationError("A buy cannot contain dividend income.")
        if data.external_cash_flow != -data.trade_amount:
            raise ValidationError("Buy cash flow must equal negative trade amount.")
    elif kind is TransactionKind.SELL:
        if data.shares_delta >= ZERO or data.external_cash_flow <= ZERO or data.trade_amount <= ZERO:
            raise ValidationError("A sell requires negative shares, positive external cash, and a trade amount.")
        if data.income_amount != ZERO:
            raise ValidationError("A sell cannot contain dividend income.")
        if data.external_cash_flow != data.trade_amount:
            raise ValidationError("Sell cash flow must equal trade amount.")
    elif kind is TransactionKind.DIVIDEND:
        if data.shares_delta != ZERO or data.income_amount <= ZERO:
            raise ValidationError("A paid-out dividend requires zero shares and positive income.")
        if data.external_cash_flow != data.income_amount:
            raise ValidationError("Paid-out dividend cash flow must equal dividend income.")
        if data.trade_amount != ZERO:
            raise ValidationError("A paid-out dividend cannot contain a trade.")
    elif kind is TransactionKind.REINVESTED_DIVIDEND:
        if data.shares_delta <= ZERO or data.income_amount <= ZERO or data.trade_amount <= ZERO:
            raise ValidationError("A reinvested dividend requires positive shares, income, and acquisition cost.")
        residual = data.income_amount - data.trade_amount
        if data.external_cash_flow != residual:
            raise ValidationError(
                "Reinvestment cash flow must classify the dividend remainder or owner top-up."
            )
    elif kind is TransactionKind.OPENING_POSITION:
        if data.shares_delta <= ZERO or data.external_cash_flow != ZERO or data.income_amount != ZERO:
            raise ValidationError("An opening position requires positive shares and zero cash/income.")
    elif kind is TransactionKind.LEGACY_CASH_FLOW:
        if data.shares_delta != ZERO or data.trade_amount != ZERO or data.income_amount != ZERO:
            raise ValidationError("A legacy cash flow cannot contain shares, a trade, or income.")
        if data.external_cash_flow == ZERO:
            raise ValidationError("A legacy cash flow cannot be zero.")
    return data


def snapshot(transaction: Transaction) -> dict[str, Any]:
    fields = (
        "portfolio_id", "security_id", "kind", "trade_date", "shares_delta",
        "external_cash_flow", "trade_amount", "income_amount", "source_key", "deleted_at",
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


def _assert_nonnegative_ledger(session: Session, portfolio_id: int, security_id: int | None) -> None:
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
            raise ValidationError(f"Transaction {row.id} would make holdings negative on {row.trade_date}.")


def create_transaction(session: Session, data: TransactionInput) -> Transaction:
    data = validate(data)
    transaction = Transaction()
    _apply(transaction, data)
    session.add(transaction)
    session.flush()
    _assert_nonnegative_ledger(session, data.portfolio_id, data.security_id)
    return transaction


def edit_transaction(session: Session, transaction_id: int, data: TransactionInput) -> Transaction:
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
    session.add(TransactionAudit(transaction_id=transaction.id, action="EDIT", before=before, after=snapshot(transaction)))
    return transaction


def delete_transaction(session: Session, transaction_id: int) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is not None:
        raise ValidationError("Active transaction not found.")
    before = snapshot(transaction)
    transaction.deleted_at = datetime.now(timezone.utc)
    session.flush()
    _assert_nonnegative_ledger(session, transaction.portfolio_id, transaction.security_id)
    session.add(TransactionAudit(transaction_id=transaction.id, action="DELETE", before=before, after=snapshot(transaction)))
    return transaction


def restore_transaction(session: Session, transaction_id: int) -> Transaction:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None or transaction.deleted_at is None:
        raise ValidationError("Deleted transaction not found.")
    before = snapshot(transaction)
    transaction.deleted_at = None
    session.flush()
    _assert_nonnegative_ledger(session, transaction.portfolio_id, transaction.security_id)
    session.add(TransactionAudit(transaction_id=transaction.id, action="RESTORE", before=before, after=snapshot(transaction)))
    return transaction
