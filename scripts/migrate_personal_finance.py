"""Add the Personal Finance tables to an existing v1 database.

This is intentionally a one-time development script.  It does not change
``PRAGMA user_version`` and is not part of application startup.  A SQLite
backup is created immediately before the two tables are added.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect

from financial_hub.database import (
    SCHEMA_VERSION,
    backup_database,
    create_database_engine,
    default_database_path,
)
from financial_hub.models import Base

PERSONAL_FINANCE_TABLES = (
    "personal_finance_monthly",
    "personal_finance_annual",
)
LEGACY_TABLES = {"portfolios", "securities", "transactions", "quotes"}


@dataclass(frozen=True, slots=True)
class MigrationResult:
    database: Path
    changed: bool
    backup: Path | None
    added_tables: tuple[str, ...]


def _default_backup_path(database: Path) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return database.with_name(
        f"{database.stem}.pre-personal-finance-{timestamp}.sqlite3"
    )


def migrate_database(
    database: Path | str | None = None, backup: Path | str | None = None
) -> MigrationResult:
    """Back up and add missing Personal Finance tables to a supported database."""

    database_path = Path(database) if database is not None else default_database_path()
    database_path = database_path.resolve()
    if not database_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {database_path}")

    engine = create_database_engine(database_path)
    try:
        connection = engine.connect()
        try:
            current_version = int(
                connection.exec_driver_sql("PRAGMA user_version").scalar_one()
            )
        finally:
            connection.close()
        if current_version != SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported database schema {current_version}; expected {SCHEMA_VERSION}."
            )

        tables = set(inspect(engine).get_table_names())
        missing = tuple(name for name in PERSONAL_FINANCE_TABLES if name not in tables)
        if not missing:
            return MigrationResult(database_path, False, None, ())
        if not LEGACY_TABLES.issubset(tables):
            raise RuntimeError(
                "The database does not contain the existing Financial Hub tables."
            )

        backup_path = (
            Path(backup).resolve()
            if backup is not None
            else _default_backup_path(database_path)
        )
        if backup_path == database_path:
            raise ValueError("The backup path must differ from the active database.")
        if backup_path.exists():
            raise FileExistsError(f"Backup already exists: {backup_path}")
        backup_database(engine, backup_path)

        with engine.begin() as connection:
            for name in missing:
                Base.metadata.tables[name].create(connection, checkfirst=True)
        return MigrationResult(database_path, True, backup_path, missing)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=default_database_path(),
        help="SQLite database to update (defaults to the app database).",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        help="Optional backup path; otherwise a timestamped sibling is used.",
    )
    args = parser.parse_args(argv)
    try:
        result = migrate_database(args.database, args.backup)
    except Exception as error:  # noqa: BLE001 - CLI boundary
        parser.error(str(error))
        return 2
    if result.changed:
        print(f"Added tables: {', '.join(result.added_tables)}")
        print(f"Backup: {result.backup}")
    else:
        print("Personal Finance tables already exist; no changes made.")
    print(f"Database: {result.database}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI
    raise SystemExit(main())
