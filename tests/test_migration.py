import sqlite3

from sqlalchemy import select

from financial_hub import app as app_module
from financial_hub.app import bootstrap_new_database
from financial_hub.legacy_import import import_legacy_database
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


def test_bootstrap_syncs_finmind_before_importing_legacy(
    db, tmp_path, monkeypatch
):
    _engine, factory, _ids = db
    source = tmp_path / "legacy.db"
    _legacy_source(source)

    monkeypatch.setattr(app_module, "get_finmind_token", lambda: "token")
    monkeypatch.setattr(app_module, "FinMindProvider", lambda _token: FinMindMaster())
    bootstrap_new_database(factory, source)

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

        imported = session.scalar(
            select(Portfolio).where(Portfolio.name == "Imported portfolio")
        )
        assert imported is not None
        rows = list(
            session.scalars(
                select(Transaction)
                .where(Transaction.portfolio_id == imported.id)
                .order_by(Transaction.id)
            )
        )
        assert len(rows) == 2
        assert [row.security_id for row in rows] == [security_id, security_id]
        # Transaction amounts remain whole TWD; only quote prices are decimal.
        assert [row.amount for row in rows] == [-101, 6]


def test_legacy_import_does_not_create_legacy_security_duplicates(db, tmp_path):
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
        import_legacy_database(session, source)

    with factory() as session:
        assert session.scalar(
            select(Security.id).where(Security.symbol == "00692")
        ) is not None
