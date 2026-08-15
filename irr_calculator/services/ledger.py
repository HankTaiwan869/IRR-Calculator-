from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ..exceptions import ValidationError
from ..models import Transaction, TransactionKind

ZERO = 0


def _divide_round_half_up(numerator: int, denominator: int) -> int:
    if denominator == 0:
        raise ZeroDivisionError("Cannot divide by zero.")
    sign = -1 if (numerator < 0) != (denominator < 0) else 1
    quotient, remainder = divmod(abs(numerator), abs(denominator))
    if remainder * 2 >= abs(denominator):
        quotient += 1
    return sign * quotient


@dataclass(frozen=True, slots=True)
class LedgerResult:
    shares: int
    cost_basis: int
    average_cost: int
    realized_profit: int
    dividend_income: int
    cost_basis_complete: bool


def replay_ledger(rows: Iterable[Transaction]) -> LedgerResult:
    shares = basis = realized = dividends = ZERO
    complete = True
    for row in sorted(rows, key=lambda item: (item.trade_date, item.id or 0)):
        if row.deleted_at is not None:
            continue
        kind = TransactionKind(row.kind)
        if kind in (TransactionKind.BUY, TransactionKind.REINVESTED_DIVIDEND, TransactionKind.OPENING_POSITION):
            shares += row.shares_delta
            basis += row.trade_amount
            if kind is TransactionKind.OPENING_POSITION and row.trade_amount == ZERO:
                complete = False
            if kind is TransactionKind.REINVESTED_DIVIDEND:
                dividends += row.income_amount
        elif kind is TransactionKind.SELL:
            if shares <= ZERO or shares + row.shares_delta < ZERO:
                raise ValidationError("Ledger contains a sale exceeding the available shares.")
            sold = -row.shares_delta
            relieved = basis if sold == shares else _divide_round_half_up(basis * sold, shares)
            realized += row.external_cash_flow - relieved
            shares -= sold
            basis -= relieved
            if shares == ZERO:
                basis = ZERO
        elif kind is TransactionKind.DIVIDEND:
            dividends += row.income_amount
    return LedgerResult(
        shares=shares,
        cost_basis=basis,
        average_cost=_divide_round_half_up(basis, shares) if shares else ZERO,
        realized_profit=realized,
        dividend_income=dividends,
        cost_basis_complete=complete,
    )
