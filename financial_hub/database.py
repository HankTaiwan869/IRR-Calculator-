from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Portfolio, SchemaMeta

SCHEMA_VERSION = "4"


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    # Keep this directory stable so existing portfolios remain available when
    # the user-facing application name changes.
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
    """Create a new v4 database, or verify an existing database is v4."""
    if inspect(engine).has_table("schema_meta"):
        with Session(engine) as session:
            current = session.get(SchemaMeta, "schema_version")
        if current is None or current.value != SCHEMA_VERSION:
            actual = current.value if current is not None else "missing"
            raise RuntimeError(
                f"Unsupported database schema {actual}; this app supports schema "
                f"{SCHEMA_VERSION} only. Use a v4 database or create a new one."
            )

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        current = session.get(SchemaMeta, "schema_version")
        if current is None:
            session.add(SchemaMeta(key="schema_version", value=SCHEMA_VERSION))
            session.commit()


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
