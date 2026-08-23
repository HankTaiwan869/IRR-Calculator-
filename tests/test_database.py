import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError

from financial_hub.database import (
    create_database_engine,
    initialize_database,
)
from financial_hub.models import Portfolio, Quote, Security


def test_foreign_keys_uniqueness_and_positive_quotes(db):
    _engine, factory, (_portfolio_id, security_id) = db
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(Portfolio(name="Core"))
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(Security(provider="FinMind", symbol="2330", name_zh="duplicate"))
    with pytest.raises(IntegrityError), factory.begin() as session:
        today = __import__("datetime").date.today()
        session.add(
            Quote(
                security_id=security_id,
                market_date=today,
                refresh_cycle_date=today,
                close=0,
            )
        )


def test_fresh_database_uses_v4_single_amount_schema(tmp_path):
    path = tmp_path / "fresh.sqlite3"
    engine = create_database_engine(path)
    initialize_database(engine)

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone() == ("4",)
        transaction_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(transactions)")
        }
        assert {"shares_delta", "amount"}.issubset(transaction_columns)
        assert "deleted_at" not in transaction_columns
        assert connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'transaction_audit'
            """
        ).fetchone() is None
        assert {
            "external_cash_flow",
            "trade_amount",
            "income_amount",
            "unit_price",
            "fees",
            "notes",
        }.isdisjoint(transaction_columns)

    # Re-opening an already-supported database is a no-op.
    initialize_database(engine)
    engine.dispose()


@pytest.mark.parametrize("version", ["1", "2", "3", "5"])
def test_non_v4_database_is_rejected_without_schema_changes(tmp_path, version):
    path = tmp_path / f"v{version}.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE schema_meta (
                key VARCHAR(80) PRIMARY KEY,
                value VARCHAR(240) NOT NULL
            );
            CREATE TABLE sentinel (id INTEGER PRIMARY KEY);
        """)
        connection.execute(
            "INSERT INTO schema_meta VALUES ('schema_version', ?)", (version,)
        )

    engine = create_database_engine(path)
    with pytest.raises(RuntimeError, match=f"Unsupported database schema {version}"):
        initialize_database(engine)
    engine.dispose()

    with sqlite3.connect(path) as connection:
        assert {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        } == {"schema_meta", "sentinel"}
