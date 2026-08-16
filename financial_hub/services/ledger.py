from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..models import Transaction, TransactionKind

ZERO = 0


@dataclass(frozen=True, slots=True)
class LedgerResult:
    """Share and paid-dividend totals for one security ledger."""

    shares: int
    dividend_income: int
    opening_position_complete: bool


def replay_ledger(rows: Iterable[Transaction]) -> LedgerResult:
    shares = dividends = ZERO
    opening_complete = True
    for row in sorted(rows, key=lambda item: (item.trade_date, item.id or 0)):
        if row.deleted_at is not None:
            continue
        kind = TransactionKind(row.kind)
        if kind in (
            TransactionKind.BUY,
            TransactionKind.REINVESTED_DIVIDEND,
            TransactionKind.OPENING_POSITION,
        ):
            shares += row.shares_delta
            # Existing databases may contain an opening position with no
            # historical investment; total profit/IRR are then indeterminate.
            if kind is TransactionKind.OPENING_POSITION and row.amount >= ZERO:
                opening_complete = False
        elif kind is TransactionKind.SELL:
            shares += row.shares_delta
        elif kind is TransactionKind.DIVIDEND:
            dividends += row.amount
    return LedgerResult(
        shares=shares,
        dividend_income=dividends,
        opening_position_complete=opening_complete,
    )
