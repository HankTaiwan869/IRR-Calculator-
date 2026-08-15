import json
import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from irr_calculator.database import create_database_engine, initialize_database, session_factory
from irr_calculator.models import Portfolio, Quote, SchemaMeta, Security, Transaction, TransactionAudit


def test_foreign_keys_uniqueness_and_positive_quotes(db):
    _engine, factory, (_portfolio_id, security_id) = db
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(Portfolio(name="Core"))
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(Security(provider="FinMind", symbol="2330", name_zh="duplicate"))
    with pytest.raises(IntegrityError), factory.begin() as session:
        today = __import__("datetime").date.today()
        session.add(Quote(security_id=security_id, market_date=today, refresh_cycle_date=today, close=0))


def test_v1_decimal_schema_migrates_to_integer_columns_and_values(tmp_path):
    path = tmp_path / "v1.sqlite3"
    before = json.dumps({
        "kind": "BUY",
        "shares_delta": "1.5",
        "external_cash_flow": "-100.5",
        "trade_amount": 99.5,
        "fees": 0.5,
        "unit_price": None,
        "notes": "unchanged",
    })
    after = json.dumps({
        "kind": "SELL",
        "trade_amount": 99.5,
        "fees": 0.5,
        "income_amount": "1.5",
        "unrelated": "2.5",
    })
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE portfolios (id INTEGER PRIMARY KEY);
            CREATE TABLE securities (id INTEGER PRIMARY KEY);
            CREATE TABLE schema_meta (key VARCHAR(80) PRIMARY KEY, value VARCHAR(240) NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '1');
            INSERT INTO portfolios VALUES (1);
            INSERT INTO securities VALUES (1);
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY, portfolio_id INTEGER NOT NULL, security_id INTEGER,
                kind VARCHAR(32) NOT NULL, trade_date DATE NOT NULL,
                shares_delta NUMERIC(24, 8) NOT NULL, external_cash_flow NUMERIC(24, 6) NOT NULL,
                trade_amount NUMERIC(24, 6) NOT NULL, income_amount NUMERIC(24, 6) NOT NULL,
                unit_price NUMERIC(24, 6), fees NUMERIC(24, 6) NOT NULL,
                notes TEXT NOT NULL, source_key VARCHAR(200), deleted_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                CONSTRAINT ck_transaction_trade_nonnegative CHECK (trade_amount >= 0),
                CONSTRAINT ck_transaction_income_nonnegative CHECK (income_amount >= 0),
                CONSTRAINT ck_transaction_fees_nonnegative CHECK (fees >= 0),
                CONSTRAINT ck_transaction_price_nonnegative CHECK (unit_price IS NULL OR unit_price >= 0),
                FOREIGN KEY(portfolio_id) REFERENCES portfolios(id),
                FOREIGN KEY(security_id) REFERENCES securities(id),
                UNIQUE (source_key)
            );
            CREATE INDEX ix_transactions_portfolio_date ON transactions (portfolio_id, trade_date, id);
            CREATE INDEX ix_transactions_security_date ON transactions (security_id, trade_date, id);
            INSERT INTO transactions VALUES (
                1, 1, 1, 'BUY', '2025-01-01', 1.5, -100.5, 99.5, 0.4, 10.5, 0.5,
                '', 'legacy:1', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            );
            CREATE TABLE quotes (
                id INTEGER PRIMARY KEY, security_id INTEGER NOT NULL, provider VARCHAR(40) NOT NULL,
                market_date DATE NOT NULL, refresh_cycle_date DATE NOT NULL,
                close NUMERIC(24, 6) NOT NULL, fetched_at DATETIME NOT NULL,
                CONSTRAINT uq_quote_security_day UNIQUE (security_id, provider, market_date),
                CONSTRAINT ck_quote_positive CHECK (close > 0),
                FOREIGN KEY(security_id) REFERENCES securities(id)
            );
            CREATE INDEX ix_quotes_security_date ON quotes (security_id, market_date);
            INSERT INTO quotes VALUES (1, 1, 'FinMind', '2025-01-01', '2025-01-01', 11.5, CURRENT_TIMESTAMP);
            CREATE TABLE transaction_audit (
                id INTEGER PRIMARY KEY, transaction_id INTEGER NOT NULL, action VARCHAR(20) NOT NULL,
                before JSON, after JSON, created_at DATETIME NOT NULL,
                FOREIGN KEY(transaction_id) REFERENCES transactions(id)
            );
        """)
        connection.execute(
            "INSERT INTO transaction_audit VALUES (1, 1, 'EDIT', ?, ?, CURRENT_TIMESTAMP)",
            (before, after),
        )

    engine = create_database_engine(path)
    initialize_database(engine)
    factory = session_factory(engine)
    with factory() as session:
        transaction = session.get(Transaction, 1)
        quote = session.get(Quote, 1)
        audit = session.get(TransactionAudit, 1)
        assert session.get(SchemaMeta, "schema_version").value == "3"
        assert (transaction.shares_delta, transaction.external_cash_flow) == (2, -101)
        assert (transaction.trade_amount, transaction.income_amount) == (101, 0)
        assert quote.close == 12
        assert audit.before == {
            "kind": "BUY",
            "shares_delta": 2,
            "external_cash_flow": -101,
            "trade_amount": 101,
        }
        assert audit.after == {
            "kind": "SELL", "trade_amount": 99, "income_amount": 2, "unrelated": "2.5"
        }

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        transaction_types = {
            row[1]: row[2] for row in connection.execute("PRAGMA table_info(transactions)")
        }
        quote_types = {row[1]: row[2] for row in connection.execute("PRAGMA table_info(quotes)")}
        assert all(transaction_types[field] == "INTEGER" for field in (
            "shares_delta", "external_cash_flow", "trade_amount", "income_amount"
        ))
        assert {"unit_price", "fees", "notes"}.isdisjoint(transaction_types)
        assert quote_types["close"] == "INTEGER"
        assert {row[1] for row in connection.execute("PRAGMA index_list(transactions)")} >= {
            "ix_transactions_portfolio_date", "ix_transactions_security_date"
        }
        assert {row[1] for row in connection.execute("PRAGMA index_list(quotes)")} >= {
            "ix_quotes_security_date"
        }
        assert {row[2] for row in connection.execute("PRAGMA foreign_key_list(transactions)")} == {
            "portfolios", "securities"
        }
        assert {row[2] for row in connection.execute("PRAGMA foreign_key_list(quotes)")} == {"securities"}
        assert {row[2] for row in connection.execute("PRAGMA foreign_key_list(transaction_audit)")} == {
            "transactions"
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE transactions SET trade_amount = -1 WHERE id = 1")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE quotes SET close = 0 WHERE id = 1")
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE transactions SET portfolio_id = 999 WHERE id = 1")
        connection.rollback()

    # Initializing an already-migrated database is a no-op.
    initialize_database(engine)
    engine.dispose()


def test_fresh_database_uses_v3_integer_schema(tmp_path):
    path = tmp_path / "fresh.sqlite3"
    engine = create_database_engine(path)
    initialize_database(engine)

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone() == ("3",)
        transaction_types = {
            row[1]: row[2] for row in connection.execute("PRAGMA table_info(transactions)")
        }
        assert all(transaction_types[field] == "INTEGER" for field in (
            "shares_delta", "external_cash_flow", "trade_amount", "income_amount"
        ))
        assert {"unit_price", "fees", "notes"}.isdisjoint(transaction_types)
        assert dict(
            (row[1], row[2]) for row in connection.execute("PRAGMA table_info(quotes)")
        )["close"] == "INTEGER"

    engine.dispose()


def test_v2_fee_columns_are_folded_into_amounts_before_removal(tmp_path):
    path = tmp_path / "v2.sqlite3"
    audit = json.dumps({
        "kind": "BUY", "trade_amount": 100, "fees": 5,
        "unit_price": 10, "notes": "retired",
    })
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE portfolios (id INTEGER PRIMARY KEY);
            CREATE TABLE securities (id INTEGER PRIMARY KEY);
            CREATE TABLE schema_meta (key VARCHAR(80) PRIMARY KEY, value VARCHAR(240) NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '2');
            INSERT INTO portfolios VALUES (1);
            INSERT INTO securities VALUES (1);
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY, portfolio_id INTEGER NOT NULL, security_id INTEGER,
                kind VARCHAR(32) NOT NULL, trade_date DATE NOT NULL,
                shares_delta INTEGER NOT NULL, external_cash_flow INTEGER NOT NULL,
                trade_amount INTEGER NOT NULL, income_amount INTEGER NOT NULL,
                unit_price INTEGER, fees INTEGER NOT NULL, notes TEXT NOT NULL,
                source_key VARCHAR(200), deleted_at DATETIME,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                FOREIGN KEY(portfolio_id) REFERENCES portfolios(id),
                FOREIGN KEY(security_id) REFERENCES securities(id), UNIQUE (source_key)
            );
            INSERT INTO transactions VALUES
                (1, 1, 1, 'BUY', '2025-01-01', 10, -105, 100, 0, 10, 5, 'buy', NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (2, 1, 1, 'SELL', '2025-02-01', -1, 90, 100, 0, 100, 10, 'sell', NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (3, 1, 1, 'REINVESTED_DIVIDEND', '2025-03-01', 1, -5, 100, 100, 100, 5, 'reinvest', NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
            CREATE TABLE transaction_audit (
                id INTEGER PRIMARY KEY, transaction_id INTEGER NOT NULL, action VARCHAR(20) NOT NULL,
                before JSON, after JSON, created_at DATETIME NOT NULL,
                FOREIGN KEY(transaction_id) REFERENCES transactions(id)
            );
        """)
        connection.execute(
            "INSERT INTO transaction_audit VALUES (1, 1, 'EDIT', ?, NULL, CURRENT_TIMESTAMP)",
            (audit,),
        )

    engine = create_database_engine(path)
    initialize_database(engine)
    factory = session_factory(engine)
    with factory() as session:
        rows = {row.id: row for row in session.scalars(select(Transaction))}
        assert {row_id: row.trade_amount for row_id, row in rows.items()} == {
            1: 105, 2: 90, 3: 105,
        }
        assert {row_id: row.external_cash_flow for row_id, row in rows.items()} == {
            1: -105, 2: 90, 3: -5,
        }
        assert session.get(TransactionAudit, 1).before == {"kind": "BUY", "trade_amount": 105}
        assert session.get(SchemaMeta, "schema_version").value == "3"

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)")}
        assert {"unit_price", "fees", "notes"}.isdisjoint(columns)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    engine.dispose()
