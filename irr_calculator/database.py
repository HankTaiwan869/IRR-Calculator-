from __future__ import annotations

import json
import os
import sqlite3
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Portfolio, SchemaMeta

SCHEMA_VERSION = "3"

_AUDIT_INTEGER_FIELDS = {
    "shares_delta",
    "external_cash_flow",
    "trade_amount",
    "income_amount",
    "unit_price",
    "fees",
}


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "IRRCalculator"


def default_database_path() -> Path:
    return app_data_dir() / "portfolio.sqlite3"


def create_database_engine(path: Path | str | None = None) -> Engine:
    database_path = Path(path) if path is not None else default_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_path}", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        current = session.get(SchemaMeta, "schema_version")
        if current is None:
            session.add(SchemaMeta(key="schema_version", value=SCHEMA_VERSION))
            session.commit()
            return
        current_version = current.value
    if current_version == "1":
        _migrate_v1_to_v2(engine)
        current_version = "2"
    if current_version == "2":
        _migrate_v2_to_v3(engine)
    elif current_version != SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported database schema {current_version}; expected {SCHEMA_VERSION}."
        )


def _round_integer(value: object) -> int:
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _integer_snapshot(value: str | None) -> str | None:
    if value is None:
        return None
    data = json.loads(value)
    if not isinstance(data, dict):
        return value
    for field in _AUDIT_INTEGER_FIELDS:
        if data.get(field) is not None:
            data[field] = _round_integer(data[field])
    return json.dumps(data, separators=(",", ":"))


def _v3_snapshot(value: str | None) -> str | None:
    """Remove retired fields while folding fees into the accounting amount."""
    if value is None:
        return None
    data = json.loads(value)
    if not isinstance(data, dict):
        return value
    fees = _round_integer(data.pop("fees", 0) or 0)
    if data.get("trade_amount") is not None and data.get("kind") is not None:
        amount = _round_integer(data["trade_amount"])
        if data["kind"] in ("BUY", "REINVESTED_DIVIDEND"):
            data["trade_amount"] = amount + fees
        elif data["kind"] == "SELL":
            data["trade_amount"] = amount - fees
    data.pop("unit_price", None)
    data.pop("notes", None)
    return json.dumps(data, separators=(",", ":"))


def _migrate_v1_to_v2(engine: Engine) -> None:
    """Rebuild decimal-backed tables with integer columns, rounding half up."""
    raw = engine.raw_connection()
    connection: sqlite3.Connection = raw.driver_connection
    try:
        connection.commit()
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.create_function(
            "round_half_up", 1, _round_integer, deterministic=True
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            CREATE TABLE transactions_v2 (
                id INTEGER NOT NULL,
                portfolio_id INTEGER NOT NULL,
                security_id INTEGER,
                kind VARCHAR(32) NOT NULL,
                trade_date DATE NOT NULL,
                shares_delta INTEGER NOT NULL,
                external_cash_flow INTEGER NOT NULL,
                trade_amount INTEGER NOT NULL,
                income_amount INTEGER NOT NULL,
                unit_price INTEGER,
                fees INTEGER NOT NULL,
                notes TEXT NOT NULL,
                source_key VARCHAR(200),
                deleted_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT ck_transaction_trade_nonnegative CHECK (trade_amount >= 0),
                CONSTRAINT ck_transaction_income_nonnegative CHECK (income_amount >= 0),
                CONSTRAINT ck_transaction_fees_nonnegative CHECK (fees >= 0),
                CONSTRAINT ck_transaction_price_nonnegative CHECK (unit_price IS NULL OR unit_price >= 0),
                FOREIGN KEY(portfolio_id) REFERENCES portfolios (id),
                FOREIGN KEY(security_id) REFERENCES securities (id),
                UNIQUE (source_key)
            )
        """)
        connection.execute("""
            INSERT INTO transactions_v2 (
                id, portfolio_id, security_id, kind, trade_date, shares_delta,
                external_cash_flow, trade_amount, income_amount, unit_price, fees,
                notes, source_key, deleted_at, created_at, updated_at
            )
            SELECT
                id, portfolio_id, security_id, kind, trade_date,
                round_half_up(shares_delta),
                round_half_up(external_cash_flow),
                round_half_up(trade_amount),
                round_half_up(income_amount),
                CASE WHEN unit_price IS NULL THEN NULL ELSE round_half_up(unit_price) END,
                round_half_up(fees), notes, source_key, deleted_at, created_at, updated_at
            FROM transactions
        """)
        connection.execute("""
            CREATE TABLE quotes_v2 (
                id INTEGER NOT NULL,
                security_id INTEGER NOT NULL,
                provider VARCHAR(40) NOT NULL,
                market_date DATE NOT NULL,
                refresh_cycle_date DATE NOT NULL,
                close INTEGER NOT NULL,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT uq_quote_security_day UNIQUE (security_id, provider, market_date),
                CONSTRAINT ck_quote_positive CHECK (close > 0),
                FOREIGN KEY(security_id) REFERENCES securities (id)
            )
        """)
        connection.execute("""
            INSERT INTO quotes_v2 (
                id, security_id, provider, market_date, refresh_cycle_date, close, fetched_at
            )
            SELECT id, security_id, provider, market_date, refresh_cycle_date,
                   round_half_up(close), fetched_at
            FROM quotes
        """)
        audit_rows = list(
            connection.execute(
                "SELECT id, transaction_id, action, before, after, created_at FROM transaction_audit"
            )
        )

        connection.execute("DROP TABLE transaction_audit")
        connection.execute("DROP TABLE quotes")
        connection.execute("DROP TABLE transactions")
        connection.execute("ALTER TABLE transactions_v2 RENAME TO transactions")
        connection.execute("ALTER TABLE quotes_v2 RENAME TO quotes")
        connection.execute("""
            CREATE TABLE transaction_audit (
                id INTEGER NOT NULL,
                transaction_id INTEGER NOT NULL,
                action VARCHAR(20) NOT NULL,
                before JSON,
                after JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(transaction_id) REFERENCES transactions (id)
            )
        """)
        for audit in audit_rows:
            connection.execute(
                "INSERT INTO transaction_audit VALUES (?, ?, ?, ?, ?, ?)",
                (
                    audit[0],
                    audit[1],
                    audit[2],
                    _integer_snapshot(audit[3]),
                    _integer_snapshot(audit[4]),
                    audit[5],
                ),
            )
        connection.execute(
            "CREATE INDEX ix_transactions_portfolio_date ON transactions (portfolio_id, trade_date, id)"
        )
        connection.execute(
            "CREATE INDEX ix_transactions_security_date ON transactions (security_id, trade_date, id)"
        )
        connection.execute(
            "CREATE INDEX ix_quotes_security_date ON quotes (security_id, market_date)"
        )
        connection.execute(
            "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
            ("2",),
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"Database migration failed foreign-key validation: {violations}"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
        raw.close()


def _migrate_v2_to_v3(engine: Engine) -> None:
    """Drop retired transaction fields without changing accounting outcomes."""
    raw = engine.raw_connection()
    connection: sqlite3.Connection = raw.driver_connection
    try:
        connection.commit()
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""
            CREATE TABLE transactions_v3 (
                id INTEGER NOT NULL,
                portfolio_id INTEGER NOT NULL,
                security_id INTEGER,
                kind VARCHAR(32) NOT NULL,
                trade_date DATE NOT NULL,
                shares_delta INTEGER NOT NULL,
                external_cash_flow INTEGER NOT NULL,
                trade_amount INTEGER NOT NULL,
                income_amount INTEGER NOT NULL,
                source_key VARCHAR(200),
                deleted_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT ck_transaction_trade_nonnegative CHECK (trade_amount >= 0),
                CONSTRAINT ck_transaction_income_nonnegative CHECK (income_amount >= 0),
                FOREIGN KEY(portfolio_id) REFERENCES portfolios (id),
                FOREIGN KEY(security_id) REFERENCES securities (id),
                UNIQUE (source_key)
            )
        """)
        connection.execute("""
            INSERT INTO transactions_v3 (
                id, portfolio_id, security_id, kind, trade_date, shares_delta,
                external_cash_flow, trade_amount, income_amount, source_key,
                deleted_at, created_at, updated_at
            )
            SELECT
                id, portfolio_id, security_id, kind, trade_date, shares_delta,
                external_cash_flow,
                CASE
                    WHEN kind IN ('BUY', 'REINVESTED_DIVIDEND') THEN trade_amount + fees
                    WHEN kind = 'SELL' THEN trade_amount - fees
                    ELSE trade_amount
                END,
                income_amount, source_key, deleted_at, created_at, updated_at
            FROM transactions
        """)
        audit_rows = list(
            connection.execute(
                "SELECT id, transaction_id, action, before, after, created_at FROM transaction_audit"
            )
        )
        connection.execute("DROP TABLE transaction_audit")
        connection.execute("DROP TABLE transactions")
        connection.execute("ALTER TABLE transactions_v3 RENAME TO transactions")
        connection.execute("""
            CREATE TABLE transaction_audit (
                id INTEGER NOT NULL,
                transaction_id INTEGER NOT NULL,
                action VARCHAR(20) NOT NULL,
                before JSON,
                after JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(transaction_id) REFERENCES transactions (id)
            )
        """)
        for audit in audit_rows:
            connection.execute(
                "INSERT INTO transaction_audit VALUES (?, ?, ?, ?, ?, ?)",
                (
                    audit[0],
                    audit[1],
                    audit[2],
                    _v3_snapshot(audit[3]),
                    _v3_snapshot(audit[4]),
                    audit[5],
                ),
            )
        connection.execute(
            "CREATE INDEX ix_transactions_portfolio_date ON transactions (portfolio_id, trade_date, id)"
        )
        connection.execute(
            "CREATE INDEX ix_transactions_security_date ON transactions (security_id, trade_date, id)"
        )
        connection.execute(
            "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
            (SCHEMA_VERSION,),
        )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"Database migration failed foreign-key validation: {violations}"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
        raw.close()


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def ensure_default_portfolio(session: Session) -> int:
    portfolio_id = session.scalar(select(Portfolio.id).limit(1))
    if portfolio_id is not None:
        return portfolio_id
    portfolio = Portfolio(name="My Portfolio")
    session.add(portfolio)
    session.flush()
    return portfolio.id


def backup_database(engine: Engine, destination: Path | str) -> Path:
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(str(engine.url.database)).resolve()
    if target == source_path:
        raise ValueError("Choose a backup path different from the active database.")
    raw = engine.raw_connection()
    try:
        with sqlite3.connect(target) as output:
            raw.driver_connection.backup(output)
    finally:
        raw.close()
    return target
