from __future__ import annotations

from datetime import date, datetime

from PyQt6.QtCore import QSortFilterProxyModel, Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QDialog, QMessageBox
from sqlalchemy import func, select

from financial_hub import __version__
from financial_hub.exceptions import ValidationError
from financial_hub.models import (
    Portfolio,
    Quote,
    Transaction,
    TransactionAudit,
    TransactionKind,
)
from financial_hub.services.transactions import TransactionInput
from financial_hub.ui.main_window import MainWindow
from financial_hub.ui.models import TransactionTableModel
from financial_hub.ui.table_selection import (
    SelectionIndicatorHeader,
    UnhighlightedSelectionDelegate,
)


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
        "financial_hub.ui.views.portfolios.PortfolioDialog",
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


def test_settings_label_and_sidebar_version(qtbot, db):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)

    assert window.PAGE_NAMES[-1] == "Settings"
    assert window.nav_buttons[-1].text() == "Settings"
    assert window.version_label.text() == f"Version {__version__}"


def test_table_selection_uses_a_single_left_check(qtbot, db):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    window.history.model.set_rows(
        [(99, date(2026, 1, 1), "Core", "2330", "BUY", 1, -100)]
    )

    for table in (window.portfolios.table, window.history.table):
        assert isinstance(table.itemDelegate(), UnhighlightedSelectionDelegate)
        assert isinstance(table.verticalHeader(), SelectionIndicatorHeader)
        assert table.editTriggers() == table.EditTrigger.NoEditTriggers
        table.selectRow(0)
        assert table.verticalHeader().indicator_text(0) == "✓"


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
            amount=-100,
        )
        session.add(transaction)
        session.flush()
        session.add(
            TransactionAudit(
                transaction_id=transaction.id,
                action="EDIT",
                before={"amount": -90},
                after={"amount": -100},
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
        "financial_hub.ui.views.portfolios.PortfolioDialog",
        _AcceptedPortfolioDialog,
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    changes = QSignalSpy(window.portfolios.data_changed)

    window.portfolios.create()

    assert len(changes) == 0


def test_history_delete_is_permanent_and_refreshes_summaries(qtbot, db, monkeypatch):
    _engine, factory, (portfolio_id, security_id) = db
    today = datetime.now().astimezone().date()
    with factory.begin() as session:
        transaction = Transaction(
            portfolio_id=portfolio_id,
            security_id=security_id,
            kind=TransactionKind.BUY.value,
            trade_date=today,
            shares_delta=10,
            amount=-100,
        )
        session.add_all(
            (
                Transaction(
                    portfolio_id=portfolio_id,
                    security_id=security_id,
                    kind=TransactionKind.BUY.value,
                    trade_date=today,
                    shares_delta=50,
                    amount=-500,
                    deleted_at=datetime.now().astimezone(),
                ),
                transaction,
                Quote(
                    security_id=security_id,
                    provider="FinMind",
                    market_date=today,
                    refresh_cycle_date=today,
                    close=12,
                ),
            )
        )
        session.flush()
        transaction_id = transaction.id

    window = MainWindow(factory)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    changes = QSignalSpy(window.history.data_changed)
    assert window.dashboard.cards["Total assets"].value.text() == "NT$ 120"
    assert window.history.model.rowCount() == 1
    assert window.portfolios.table.item(0, 2).text() == "1"

    window.history.table.selectRow(0)
    window.history.delete_selected()

    assert len(changes) == 1
    assert window.dashboard.cards["Total assets"].value.text() == "NT$ 0"
    assert window.history.model.rowCount() == 0
    assert window.portfolios.table.item(0, 2).text() == "0"
    with factory() as session:
        assert session.get(Transaction, transaction_id) is None


def test_history_edit_emits_only_after_success(qtbot, db, monkeypatch):
    _engine, factory, (portfolio_id, security_id) = db
    with factory.begin() as session:
        transaction = Transaction(
            portfolio_id=portfolio_id,
            security_id=security_id,
            kind=TransactionKind.BUY.value,
            trade_date=date(2025, 1, 1),
            shares_delta=10,
            amount=-100,
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
            amount=-120,
        )

        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            return self.DialogCode.Accepted

    window = MainWindow(factory)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "financial_hub.ui.views.history.TransactionDialog",
        AcceptedTransactionDialog,
    )
    changes = QSignalSpy(window.history.data_changed)
    window.history.table.selectRow(0)

    window.history.edit_selected()

    assert len(changes) == 1
    with factory() as session:
        edited = session.get(Transaction, transaction_id)
        assert edited.trade_date == date(2025, 1, 2)
        assert edited.amount == -120

    monkeypatch.setattr(
        "financial_hub.ui.views.history.edit_transaction",
        lambda *_args: (_ for _ in ()).throw(ValidationError("bad")),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    window.history.table.selectRow(0)
    window.history.edit_selected()
    assert len(changes) == 1


def test_history_proxy_sorts_native_dates_and_numbers_and_keeps_ids(qtbot):
    model = TransactionTableModel(
        [
            (10, date(2025, 10, 1), "Core", "2330", "BUY", 10, 100),
            (20, date(2024, 2, 1), "Core", "2330", "BUY", 2, 20),
            (30, date(2025, 2, 1), "Core", "2330", "BUY", 100, 3),
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

    proxy.sort(5, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(row, 5).data(Qt.ItemDataRole.UserRole) for row in range(3)] == [
        30,
        20,
        10,
    ]
