from __future__ import annotations

from datetime import date
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QDate, QModelIndex, Qt

ROOT_INDEX = QModelIndex()


class TransactionTableModel(QAbstractTableModel):
    HEADERS = (
        "Date",
        "Portfolio",
        "Security",
        "Type",
        "Shares",
        "Amount",
    )
    SORT_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, rows: list[Any] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.rows = rows or []

    def set_rows(self, rows: list[Any]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role=Qt.ItemDataRole.DisplayRole,
    ):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
        ):
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row[0]
        if role == self.SORT_ROLE:
            value = row[index.column() + 1]
            if isinstance(value, date):
                return QDate(value.year, value.month, value.day)
            return value
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        values = row[1:]
        value = values[index.column()]
        if role == Qt.ItemDataRole.DisplayRole and index.column() in (4, 5):
            return f"{int(value):,}"
        return str(value) if role == Qt.ItemDataRole.DisplayRole else value
