from __future__ import annotations

from PyQt6.QtCore import QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ...exceptions import ValidationError
from ...models import Portfolio, Security, Transaction
from ...services.transactions import (
    delete_transaction,
    edit_transaction,
)
from ..dialogs import TransactionDialog
from ..models import TransactionTableModel
from ..table_selection import use_check_row_selection


class HistoryView(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 12, 20)
        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter portfolio, security, type, or date…")
        toolbar.addWidget(self.search, 1)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("danger")
        edit_button = QPushButton("Edit")
        toolbar.addWidget(edit_button)
        toolbar.addWidget(self.delete_button)
        layout.addLayout(toolbar)

        self.model = TransactionTableModel()
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(TransactionTableModel.SORT_ROLE)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        use_check_row_selection(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.delete_button.clicked.connect(self.delete_selected)
        edit_button.clicked.connect(self.edit_selected)
        self.reload()

    def reload(self) -> None:
        with self.factory() as session:
            records = session.execute(
                select(Transaction, Portfolio.name, Security.symbol)
                .join(Portfolio, Portfolio.id == Transaction.portfolio_id)
                .outerjoin(Security, Security.id == Transaction.security_id)
                .order_by(Transaction.trade_date.desc(), Transaction.id.desc())
            ).all()
        rows = []
        for transaction, portfolio, symbol in records:
            rows.append(
                (
                    transaction.id,
                    transaction.trade_date,
                    portfolio,
                    symbol or "—",
                    transaction.kind.replace("_", " "),
                    transaction.shares_delta,
                    transaction.amount,
                )
            )
        self.model.set_rows(rows)
        self.table.resizeColumnsToContents()

    def _selected_id(self) -> int | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "History", "Select a transaction first.")
            return None
        source = self.proxy.mapToSource(indexes[0])
        return int(self.model.data(source, Qt.ItemDataRole.UserRole))

    def delete_selected(self) -> None:
        transaction_id = self._selected_id()
        if (
            transaction_id is None
            or QMessageBox.question(
                self,
                "Delete transaction",
                "Permanently delete the selected transaction? This cannot be undone.",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            with self.factory.begin() as session:
                delete_transaction(session, transaction_id)
        except ValidationError as error:
            QMessageBox.warning(self, "Delete transaction", str(error))
            return
        self.data_changed.emit()

    def edit_selected(self) -> None:
        transaction_id = self._selected_id()
        if transaction_id is None:
            return
        with self.factory() as session:
            transaction = session.get(Transaction, transaction_id)
        dialog = TransactionDialog(self.factory, transaction, self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.result_data is None:
            return
        try:
            with self.factory.begin() as session:
                edit_transaction(session, transaction_id, dialog.result_data)
        except ValidationError as error:
            QMessageBox.warning(self, "Edit transaction", str(error))
            return
        self.data_changed.emit()
