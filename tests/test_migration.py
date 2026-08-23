import sqlite3
from datetime import date

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from financial_hub import app as app_module
from financial_hub.app import bootstrap_new_database
from financial_hub.data_import import import_transactions
from financial_hub.exceptions import ValidationError
from financial_hub.models import Portfolio, Security, Transaction
from financial_hub.providers.base import SecurityInfo


class FinMindMaster:
    name = "FinMind"

    def security_master(self):
        return (
            SecurityInfo(
                symbol="00692",
                name_zh="富邦公司治理",
                exchange="twse",
                security_type="etf",
            ),
        )


def _legacy_source(path):
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE log(id INTEGER PRIMARY KEY, stock_code TEXT, time TEXT, amount NUMERIC)"
        )
        connection.executemany(
            "INSERT INTO log VALUES (?, ?, ?, ?)",
            [
                (1, "00692", "2024-01-01", -100.5),
                (2, "00692", "2024-06-01", 5.5),
            ],
        )


def test_bootstrap_syncs_finmind_without_importing_a_legacy_file(db, monkeypatch):
    _engine, factory, _ids = db

    monkeypatch.setattr(app_module, "get_finmind_token", lambda: "token")
    monkeypatch.setattr(app_module, "FinMindProvider", lambda _token: FinMindMaster())
    bootstrap_new_database(factory)

    with factory() as session:
        security = session.scalar(
            select(Security).where(Security.symbol == "00692")
        )
        assert security is not None
        security_id = security.id
        securities = list(
            session.scalars(select(Security).where(Security.symbol == "00692"))
        )
        assert len(securities) == 1
        assert securities[0].id == security_id
        assert securities[0].name_zh == "富邦公司治理"
        assert securities[0].exchange == "twse"
        assert securities[0].security_type == "etf"

        assert session.scalar(
            select(Portfolio).where(Portfolio.name == "Imported portfolio")
        ) is None


def test_sqlite_import_does_not_create_security_duplicates(db, tmp_path):
    _engine, factory, _ids = db
    source = tmp_path / "legacy.db"
    _legacy_source(source)

    with factory.begin() as session:
        session.add(
            Security(
                symbol="00692",
                name_zh="富邦公司治理",
                exchange="twse",
                security_type="etf",
            )
        )

    with factory.begin() as session:
        result = import_transactions(session, source)

    assert result.imported_rows == 2

    with factory() as session:
        assert session.scalar(
            select(Security.id).where(Security.symbol == "00692")
        ) is not None


def test_excel_import_uses_the_same_transaction_pipeline(db, tmp_path):
    _engine, factory, _ids = db
    source = tmp_path / "cash-flows.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(("id", "stock_code", "date", "amount"))
    sheet.append((1, "2330", date(2024, 1, 1), -100.5))
    sheet.append((2, "2330", "2024-06-01", 5.5))
    workbook.save(source)

    with factory.begin() as session:
        result = import_transactions(session, source)

    assert result.imported_rows == 2
    with factory() as session:
        portfolio = session.scalar(
            select(Portfolio).where(Portfolio.name == "Imported portfolio")
        )
        assert portfolio is not None
        rows = list(
            session.scalars(
                select(Transaction)
                .where(Transaction.portfolio_id == portfolio.id)
                .order_by(Transaction.id)
            )
        )
        assert [row.amount for row in rows] == [-101, 6]


def test_excel_import_requires_its_hard_coded_schema(db, tmp_path):
    _engine, factory, _ids = db
    source = tmp_path / "cash-flows.xlsx"
    workbook = Workbook()
    workbook.active.append(("id", "stock_code", "amount"))
    workbook.save(source)

    with (
        factory.begin() as session,
        pytest.raises(ValidationError, match="missing required columns: date"),
    ):
        import_transactions(session, source)
