from __future__ import annotations

from datetime import date, datetime

from PyQt6.QtCore import QSortFilterProxyModel, Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QDialog, QMessageBox
from sqlalchemy import func, select

from irr_calculator import __version__
from irr_calculator.exceptions import ValidationError
from irr_calculator.models import (
    Portfolio,
    Quote,
    Transaction,
    TransactionAudit,
    TransactionKind,
)
from irr_calculator.services.transactions import TransactionInput
from irr_calculator.ui.main_window import MainWindow
from irr_calculator.ui.models import TransactionTableModel


def _combo_items(combo):
    return [combo.itemText(index) for index in range(combo.count())]


def _select_portfolio(view, name: str) -> None:
    for row in range(view.table.rowCount()):
        if view.table.item(row, 0).text() == name:
            view.table.selectRow(row)
            return
    raise AssertionError(f"Portfolio {name!r} was not found")


class _AcceptedPortfolioDialog:
    DialogCode = QDialog.DialogCode
    portfolio_name = "Growth"

    def __init__(self, *_args, **_kwargs):
        pass

    def exec(self):
        return self.DialogCode.Accepted


def test_portfolio_changes_refresh_dependent_selectors(qtbot, db, monkeypatch):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    _AcceptedPortfolioDialog.portfolio_name = "Growth"
    monkeypatch.setattr(
        "irr_calculator.ui.views.portfolios.PortfolioDialog",
        _AcceptedPortfolioDialog,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    window.portfolios.create()

    assert _combo_items(window.dashboard.portfolio) == [
        "All portfolios",
        "Core",
        "Growth",
    ]
    assert _combo_items(window.transactions.portfolio) == ["Core", "Growth"]

    _select_portfolio(window.portfolios, "Growth")
    window.portfolios.archive_restore()
    assert _combo_items(window.dashboard.portfolio) == ["All portfolios", "Core"]
    assert _combo_items(window.transactions.portfolio) == ["Core"]

    _select_portfolio(window.portfolios, "Growth")
    window.portfolios.archive_restore()
    assert "Growth" in _combo_items(window.dashboard.portfolio)

    _AcceptedPortfolioDialog.portfolio_name = "Long term"
    _select_portfolio(window.portfolios, "Growth")
    window.portfolios.rename()
    assert "Long term" in _combo_items(window.dashboard.portfolio)
    assert "Growth" not in _combo_items(window.transactions.portfolio)

    _select_portfolio(window.portfolios, "Long term")
    window.portfolios.delete_selected()
    assert "Long term" not in _combo_items(window.dashboard.portfolio)
    assert "Long term" not in _combo_items(window.transactions.portfolio)


def test_settings_label_and_version(qtbot, db):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)

    assert window.PAGE_NAMES[-1] == "Settings"
    assert window.nav_buttons[-1].text() == "Settings"
    assert window.settings.version_value.text() == __version__


def test_nonempty_portfolio_delete_removes_transactions_and_audits(
    qtbot, db, monkeypatch
):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        transaction = Transaction(
            portfolio_id=portfolio_id,
            security_id=security_id,
            kind=TransactionKind.BUY.value,
            trade_date=datetime.now().astimezone().date(),
            shares_delta=1,
            external_cash_flow=-100,
            trade_amount=100,
            income_amount=0,
        )
        session.add(transaction)
        session.flush()
        session.add(
            TransactionAudit(
                transaction_id=transaction.id,
                action="EDIT",
                before={"trade_amount": 90},
                after={"trade_amount": 100},
            )
        )

    window = MainWindow(factory)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    changes = QSignalSpy(window.portfolios.data_changed)
    _select_portfolio(window.portfolios, "Core")

    window.portfolios.delete_selected()

    assert len(changes) == 1
    with factory() as session:
        assert session.get(Portfolio, portfolio_id) is None
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0
        assert session.scalar(select(func.count()).select_from(TransactionAudit)) == 0
    assert _combo_items(window.transactions.portfolio) == []


def test_failed_portfolio_create_does_not_emit_change(qtbot, db, monkeypatch):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    _AcceptedPortfolioDialog.portfolio_name = "Core"
    monkeypatch.setattr(
        "irr_calculator.ui.views.portfolios.PortfolioDialog",
        _AcceptedPortfolioDialog,
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    changes = QSignalSpy(window.portfolios.data_changed)

    window.portfolios.create()

    assert len(changes) == 0


def test_history_delete_and_restore_refresh_dashboard(qtbot, db, monkeypatch):
    _engine, factory, (portfolio_id, security_id) = db
    today = datetime.now().astimezone().date()
    with factory.begin() as session:
        session.add_all(
            (
                Transaction(
                    portfolio_id=portfolio_id,
                    security_id=security_id,
                    kind=TransactionKind.BUY.value,
                    trade_date=today,
                    shares_delta=10,
                    external_cash_flow=-100,
                    trade_amount=100,
                    income_amount=0,
                ),
                Quote(
                    security_id=security_id,
                    provider="FinMind",
                    market_date=today,
                    refresh_cycle_date=today,
                    close=12,
                ),
            )
        )

    window = MainWindow(factory)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    changes = QSignalSpy(window.history.data_changed)
    assert window.dashboard.cards["Total assets"].value.text() == "NT$ 120"

    window.history.table.selectRow(0)
    window.history.delete_selected()

    assert len(changes) == 1
    assert window.dashboard.cards["Total assets"].value.text() == "NT$ 0"
    assert window.history.model.index(0, 7).data() == "Deleted"

    window.history.table.selectRow(0)
    window.history.restore_selected()

    assert len(changes) == 2
    assert window.dashboard.cards["Total assets"].value.text() == "NT$ 120"
    assert window.history.model.index(0, 7).data() == "Active"


def test_history_edit_emits_only_after_success(qtbot, db, monkeypatch):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        transaction = Transaction(
            portfolio_id=portfolio_id,
            security_id=security_id,
            kind=TransactionKind.BUY.value,
            trade_date=date(2025, 1, 1),
            shares_delta=10,
            external_cash_flow=-100,
            trade_amount=100,
            income_amount=0,
        )
        session.add(transaction)
        session.flush()
        transaction_id = transaction.id

    class AcceptedTransactionDialog:
        DialogCode = QDialog.DialogCode
        result_data = TransactionInput(
            portfolio_id=portfolio_id,
            security_id=security_id,
            kind=TransactionKind.BUY,
            trade_date=date(2025, 1, 2),
            shares_delta=10,
            external_cash_flow=-120,
            trade_amount=120,
        )

        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return self.DialogCode.Accepted

    window = MainWindow(factory)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "irr_calculator.ui.views.history.TransactionDialog",
        AcceptedTransactionDialog,
    )
    changes = QSignalSpy(window.history.data_changed)
    window.history.table.selectRow(0)

    window.history.edit_selected()

    assert len(changes) == 1
    with factory() as session:
        edited = session.get(Transaction, transaction_id)
        assert edited.trade_date == date(2025, 1, 2)
        assert edited.trade_amount == 120

    monkeypatch.setattr(
        "irr_calculator.ui.views.history.edit_transaction",
        lambda *_args: (_ for _ in ()).throw(ValidationError("bad")),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    window.history.table.selectRow(0)
    window.history.edit_selected()
    assert len(changes) == 1


def test_history_proxy_sorts_native_dates_and_numbers_and_keeps_ids(qtbot):
    model = TransactionTableModel(
        [
            (10, date(2025, 10, 1), "Core", "2330", "BUY", 10, -2, 100, "Active"),
            (20, date(2024, 2, 1), "Core", "2330", "BUY", 2, -100, 20, "Active"),
            (30, date(2025, 2, 1), "Core", "2330", "BUY", 100, -10, 3, "Active"),
        ]
    )
    proxy = QSortFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.setSortRole(TransactionTableModel.SORT_ROLE)

    proxy.sort(0, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(3)] == [
        20,
        30,
        10,
    ]

    proxy.sort(4, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(row, 4).data(Qt.ItemDataRole.UserRole) for row in range(3)] == [
        20,
        10,
        30,
    ]

    proxy.sort(6, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(row, 6).data(Qt.ItemDataRole.UserRole) for row in range(3)] == [
        30,
        20,
        10,
    ]
