from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ...models import Portfolio, Transaction
from ..dialogs import PortfolioDialog


class PortfoliosView(QWidget):
    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 12, 20)
        actions = QHBoxLayout()
        actions.addStretch()
        new_button = QPushButton("New Portfolio")
        new_button.setObjectName("primary")
        edit_button = QPushButton("Rename")
        archive_button = QPushButton("Archive / Restore")
        delete_button = QPushButton("Delete Empty")
        delete_button.setObjectName("danger")
        for button in (new_button, edit_button, archive_button, delete_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(("Name", "Status", "Transactions"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        new_button.clicked.connect(self.create)
        edit_button.clicked.connect(self.rename)
        archive_button.clicked.connect(self.archive_restore)
        delete_button.clicked.connect(self.delete_empty)
        self.reload()

    def reload(self) -> None:
        with self.factory() as session:
            records = session.execute(select(Portfolio, func.count(Transaction.id)).outerjoin(Transaction).group_by(Portfolio.id).order_by(Portfolio.name)).all()
        self.table.setRowCount(len(records))
        for row, (portfolio, count) in enumerate(records):
            name = QTableWidgetItem(portfolio.name)
            name.setData(Qt.ItemDataRole.UserRole, portfolio.id)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem("Archived" if portfolio.archived_at else "Active"))
            self.table.setItem(row, 2, QTableWidgetItem(str(count)))

    def _selected(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Portfolios", "Select a portfolio first.")
            return None
        return int(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))

    def create(self) -> None:
        dialog = PortfolioDialog(parent=self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            with self.factory.begin() as session:
                session.add(Portfolio(name=dialog.portfolio_name))
        except IntegrityError:
            QMessageBox.warning(self, "Portfolio", "Portfolio names must be unique.")
        self.reload()

    def rename(self) -> None:
        portfolio_id = self._selected()
        if portfolio_id is None:
            return
        with self.factory() as session:
            name = session.get(Portfolio, portfolio_id).name
        dialog = PortfolioDialog(name, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            try:
                with self.factory.begin() as session:
                    session.get(Portfolio, portfolio_id).name = dialog.portfolio_name
            except IntegrityError:
                QMessageBox.warning(self, "Portfolio", "Portfolio names must be unique.")
            self.reload()

    def archive_restore(self) -> None:
        portfolio_id = self._selected()
        if portfolio_id is None:
            return
        with self.factory.begin() as session:
            portfolio = session.get(Portfolio, portfolio_id)
            portfolio.archived_at = None if portfolio.archived_at else datetime.now(timezone.utc)
        self.reload()

    def delete_empty(self) -> None:
        portfolio_id = self._selected()
        if portfolio_id is None:
            return
        with self.factory.begin() as session:
            count = session.scalar(select(func.count()).select_from(Transaction).where(Transaction.portfolio_id == portfolio_id))
            if count:
                QMessageBox.warning(self, "Portfolio", "Only empty portfolios can be permanently deleted. Archive this portfolio instead.")
                return
            session.delete(session.get(Portfolio, portfolio_id))
        self.reload()
