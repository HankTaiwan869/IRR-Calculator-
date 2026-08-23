import sqlite3

from sqlalchemy import func, select

from financial_hub.legacy_import import (
    import_legacy_database,
    reconcile_opening_position,
)
from financial_hub.models import ImportRun, Portfolio, Transaction
from financial_hub.services.analytics import replay_ledger


def test_legacy_import_is_idempotent_and_reconcilable(db, tmp_path):
    _engine, factory, _ids = db
    source = tmp_path / "legacy.db"
    with sqlite3.connect(source) as connection:
        connection.execute(
            "CREATE TABLE log(id INTEGER PRIMARY KEY, stock_code TEXT, time TEXT, amount NUMERIC)"
        )
        connection.executemany(
            "INSERT INTO log VALUES (?, ?, ?, ?)",
            [(1, "0050", "2024-01-01", -100), (2, "0050", "2024-06-01", 5)],
        )
    backup_dir = tmp_path / "backups"
    with factory.begin() as session:
        first = import_legacy_database(session, source, backup_dir)
    with factory.begin() as session:
        second = import_legacy_database(session, source, backup_dir)
    assert first.imported_rows == 2 and not first.already_imported
    assert second.already_imported
    assert first.backup_path.is_file()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ImportRun)) == 1
        imported = session.scalar(
            select(Portfolio).where(Portfolio.name == "Imported portfolio")
        )
        rows = list(
            session.scalars(
                select(Transaction).where(Transaction.portfolio_id == imported.id)
            )
        )
        assert sum((item.amount for item in rows), 0) == -95
        security_id = rows[0].security_id
    with factory.begin() as session:
        reconcile_opening_position(
            session,
            imported.id,
            security_id,
            __import__("datetime").date(2024, 12, 31),
            10,
            100,
        )
    with factory() as session:
        ledger = replay_ledger(
            list(
                session.scalars(
                    select(Transaction).where(Transaction.portfolio_id == imported.id)
                )
            )
        )
    assert ledger.shares == 10
    assert ledger.opening_position_complete


def test_legacy_import_rounds_fractional_cash_flows_half_up(db, tmp_path):
    _engine, factory, _ids = db
    source = tmp_path / "fractional-legacy.db"
    with sqlite3.connect(source) as connection:
        connection.execute(
            "CREATE TABLE log(id INTEGER PRIMARY KEY, stock_code TEXT, time TEXT, amount NUMERIC)"
        )
        connection.executemany(
            "INSERT INTO log VALUES (?, ?, ?, ?)",
            [(1, "0050", "2024-01-01", -100.5), (2, "0050", "2024-06-01", 5.5)],
        )

    with factory.begin() as session:
        import_legacy_database(session, source, tmp_path / "backups")

    with factory() as session:
        rows = list(
            session.scalars(
                select(Transaction).where(Transaction.source_key.is_not(None))
            )
        )
    assert [row.amount for row in rows] == [-101, 6]
    assert all(type(row.amount) is int for row in rows)
