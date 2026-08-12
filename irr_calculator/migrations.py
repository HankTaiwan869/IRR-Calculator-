from __future__ import annotations

import hashlib
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .exceptions import ValidationError
from .models import ImportRun, Portfolio, Security, TransactionKind
from .services.transactions import TransactionInput, create_transaction


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported_rows: int
    already_imported: bool
    backup_path: Path | None


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def import_legacy_database(session: Session, source: Path | str, backup_dir: Path | None = None) -> ImportResult:
    path = Path(source).resolve()
    if not path.is_file():
        raise ValidationError("Legacy database does not exist.")
    fingerprint = _fingerprint(path)
    previous = session.scalar(select(ImportRun).where(ImportRun.fingerprint == fingerprint))
    if previous:
        return ImportResult(previous.imported_rows, True, None)
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        table = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='log'").fetchone()
        if table is None:
            raise ValidationError("The selected database has no legacy log table.")
        rows = connection.execute("SELECT id, stock_code, time, amount FROM log ORDER BY id").fetchall()
    target_dir = (backup_dir or path.parent).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = target_dir / f"{path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
    shutil.copy2(path, backup)
    portfolio = session.scalar(select(Portfolio).where(Portfolio.name == "Imported portfolio"))
    if portfolio is None:
        portfolio = Portfolio(name="Imported portfolio")
        session.add(portfolio)
        session.flush()
    for row_id, symbol, when, amount in rows:
        security = session.scalar(select(Security).where(Security.provider == "Legacy", Security.symbol == str(symbol)))
        if security is None:
            security = Security(provider="Legacy", symbol=str(symbol), name_zh="", exchange="", security_type="stock")
            session.add(security)
            session.flush()
        create_transaction(session, TransactionInput(
            portfolio_id=portfolio.id, security_id=security.id,
            kind=TransactionKind.LEGACY_CASH_FLOW, trade_date=date.fromisoformat(str(when)[:10]),
            external_cash_flow=Decimal(str(amount)), source_key=f"legacy:{fingerprint}:{row_id}",
            notes=f"Imported from {path.name}",
        ))
    session.add(ImportRun(fingerprint=fingerprint, source_path=str(path), imported_rows=len(rows)))
    return ImportResult(len(rows), False, backup)


def reconcile_opening_position(session: Session, portfolio_id: int, security_id: int, as_of: date, shares: Decimal, total_cost: Decimal | None = None, notes: str = ""):
    return create_transaction(session, TransactionInput(
        portfolio_id=portfolio_id, security_id=security_id,
        kind=TransactionKind.OPENING_POSITION, trade_date=as_of,
        shares_delta=shares, trade_amount=total_cost or Decimal("0"), notes=notes,
    ))
