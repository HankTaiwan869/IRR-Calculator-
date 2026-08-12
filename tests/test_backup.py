from sqlalchemy import inspect

from irr_calculator.database import backup_database, create_database_engine


def test_online_sqlite_backup_contains_schema(db, tmp_path):
    engine, _factory, _ids = db
    target = backup_database(engine, tmp_path / "backup.sqlite3")
    copied = create_database_engine(target)
    try:
        assert "transactions" in inspect(copied).get_table_names()
        assert "portfolios" in inspect(copied).get_table_names()
    finally:
        copied.dispose()
