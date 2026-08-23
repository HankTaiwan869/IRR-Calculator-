from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .exceptions import ValidationError
from .models import Portfolio, Security, TransactionKind
from .services.transactions import TransactionInput, create_transaction


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Summary of the one-time legacy bootstrap."""

    imported_rows: int


def _round_integer(value: object) -> int:
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise InvalidOperation
        return int(number.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValidationError("Legacy cash flow amount is invalid.") from error


def _read_legacy_rows(path: Path) -> list[tuple[int, str, str, object]]:
    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='log'"
            ).fetchone()
            if table is None:
                raise ValidationError("The legacy database has no log table.")
            return connection.execute(
                "SELECT id, stock_code, time, amount FROM log ORDER BY id"
            ).fetchall()
    except ValidationError:
        raise
    except sqlite3.Error as error:
        raise ValidationError(f"The legacy database could not be read: {error}") from error


def import_legacy_database(session: Session, source: Path | str) -> ImportResult:
    """Import the legacy ``log`` table into the fresh v1 database.

    FinMind's security master must already have been synced.  Every legacy
    stock code is therefore linked to the canonical FinMind ``securities``
    row; no ``Legacy`` security records or import bookkeeping are created.
    """
    path = Path(source).resolve()
    if not path.is_file():
        raise ValidationError("Legacy database does not exist.")
    rows = _read_legacy_rows(path)

    portfolio = session.scalar(
        select(Portfolio).where(Portfolio.name == "Imported portfolio")
    )
    if portfolio is None:
        portfolio = Portfolio(name="Imported portfolio")
        session.add(portfolio)
        session.flush()

    for row_id, raw_symbol, raw_date, raw_amount in rows:
        symbol = str(raw_symbol).strip()
        if not symbol:
            raise ValidationError(f"Legacy row {row_id} has no stock code.")
        security = session.scalar(select(Security).where(Security.symbol == symbol))
        if security is None:
            raise ValidationError(
                f"FinMind security master has no record for {symbol}; "
                "sync the security master before importing legacy data."
            )
        try:
            trade_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError as error:
            raise ValidationError(f"Legacy row {row_id} has an invalid date.") from error
        create_transaction(
            session,
            TransactionInput(
                portfolio_id=portfolio.id,
                security_id=security.id,
                kind=TransactionKind.LEGACY_CASH_FLOW,
                trade_date=trade_date,
                amount=_round_integer(raw_amount),
            ),
        )
    return ImportResult(imported_rows=len(rows))
