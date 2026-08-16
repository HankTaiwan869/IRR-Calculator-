from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QTableView,
)

from .theme import COLORS


class UnhighlightedSelectionDelegate(QStyledItemDelegate):
    """Keep row selection functional without painting every cell as selected."""

    def paint(self, painter, option, index) -> None:  # type: ignore[no-untyped-def]
        plain_option = QStyleOptionViewItem(option)
        plain_option.state &= ~(
            QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_HasFocus
        )
        super().paint(painter, plain_option, index)


class SelectionIndicatorHeader(QHeaderView):
    """Render a single check beside the selected row."""

    def __init__(self, table: QTableView) -> None:
        super().__init__(Qt.Orientation.Vertical, table)
        self._table = table
        self.setFixedWidth(34)
        self.setSectionsClickable(False)

    def indicator_text(self, row: int) -> str:
        selection_model = self._table.selectionModel()
        if selection_model is None:
            return ""
        selected_rows = selection_model.selectedRows()
        return "✓" if any(index.row() == row for index in selected_rows) else ""

    def paintSection(
        self, painter: QPainter, rect: QRect, logical_index: int
    ) -> None:
        if not rect.isValid():
            return

        option = QStyleOptionHeader()
        self.initStyleOption(option)
        option.rect = rect
        option.section = logical_index
        option.text = ""
        option.state &= ~QStyle.StateFlag.State_HasFocus
        self.style().drawControl(
            QStyle.ControlElement.CE_Header, option, painter, self
        )

        indicator = self.indicator_text(logical_index)
        if not indicator:
            return
        painter.save()
        painter.setPen(QColor(COLORS["primary"]))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, indicator)
        painter.restore()


def use_check_row_selection(table: QTableView) -> None:
    """Show selection only as a check in the vertical row header."""

    table.setItemDelegate(UnhighlightedSelectionDelegate(table))
    header = SelectionIndicatorHeader(table)
    table.setVerticalHeader(header)
    selection_model = table.selectionModel()
    if selection_model is not None:
        selection_model.selectionChanged.connect(header.viewport().update)
        selection_model.currentChanged.connect(header.viewport().update)
