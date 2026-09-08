from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...services.personal_finance import (
    AnnualFinanceInput,
    MonthlyFinanceInput,
    calculate_yearly_summary,
    list_annual_snapshots,
    list_monthly_records,
    upsert_annual_snapshot,
    upsert_monthly_record,
)

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _current_year() -> int:
    return datetime.now().astimezone().year


@dataclass(frozen=True)
class _MonthlyRow:
    year: int
    month: int
    income: int | None
    expenditure: int | None


@dataclass(frozen=True)
class _YearlyRow:
    year: int
    total_asset: int | None
    portfolio_value: int | None
    debt: int | None


def _amount(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        value_text = str(value).replace(",", "").strip()
        value_decimal = Decimal(value_text)
        if not value_decimal.is_finite() or value_decimal != value_decimal.to_integral_value():
            return None
        return int(value_decimal)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _monthly_row(record: object) -> _MonthlyRow:
    return _MonthlyRow(
        int(record.year),  # type: ignore[attr-defined]
        int(record.month),  # type: ignore[attr-defined]
        _amount(record.income),  # type: ignore[attr-defined]
        _amount(record.expenditure),  # type: ignore[attr-defined]
    )


def _yearly_row(record: object) -> _YearlyRow:
    return _YearlyRow(
        int(record.year),  # type: ignore[attr-defined]
        _amount(record.total_asset_excluding_investment),  # type: ignore[attr-defined]
        _amount(record.total_portfolio_value),  # type: ignore[attr-defined]
        _amount(record.total_debt),  # type: ignore[attr-defined]
    )


def _cell_text(table: QTableWidget, row: int, column: int) -> str:
    item = table.item(row, column)
    return "" if item is None else item.text().strip()


def _parse_amount(value: str) -> int | None:
    value = value.strip().replace(",", "")
    if not value:
        return None
    if not value.isdigit():
        raise ValueError("Enter a non-negative whole TWD amount, or leave it blank.")
    return int(value)


def _display_amount(value: int | None) -> str:
    return "" if value is None else f"{value:,}"


class PersonalFinanceView(QWidget):
    """Small two-tab editor for monthly cash flow and yearly asset values."""

    data_changed = pyqtSignal()

    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        self._loading = False
        self._monthly_dirty = False
        self._yearly_dirty = False
        self._monthly_loaded_year = _current_year()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 12, 20)
        layout.setSpacing(10)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_monthly_tab()
        self._build_yearly_tab()
        self.reload()

    def _build_monthly_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Year"))
        self.year_selector = QSpinBox()
        self.year_selector.setRange(1900, 2200)
        self.year_selector.setValue(_current_year())
        self.year_selector.valueChanged.connect(self._monthly_year_changed)
        toolbar.addWidget(self.year_selector)
        toolbar.addStretch()
        self.monthly_save_button = QPushButton("Save Monthly Records")
        self.monthly_save_button.setObjectName("primary")
        self.monthly_save_button.clicked.connect(self.save_monthly)
        toolbar.addWidget(self.monthly_save_button)
        layout.addLayout(toolbar)
        layout.addSpacing(16)

        self.monthly_table = QTableWidget(13, 4)
        self.monthly_table.setHorizontalHeaderLabels(
            ("Month", "Income", "Spending", "Surplus")
        )
        self.monthly_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.monthly_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self.monthly_table.verticalHeader().setVisible(False)
        self.monthly_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.monthly_table.setAlternatingRowColors(True)
        for index, name in enumerate(MONTH_NAMES):
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.monthly_table.setItem(index, 0, item)
            for column in (1, 2, 3):
                self.monthly_table.setItem(index, column, QTableWidgetItem())
                if column == 3:
                    self.monthly_table.item(index, column).setFlags(
                        self.monthly_table.item(index, column).flags()
                        & ~Qt.ItemFlag.ItemIsEditable
                    )
        self.monthly_table.itemChanged.connect(self._monthly_cell_changed)

        # final total row
        total_row = 12

        total_item = QTableWidgetItem("Total")
        total_item.setFlags(total_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.monthly_table.setItem(total_row, 0, total_item)
        for column in (1, 2, 3):
            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.monthly_table.setItem(total_row, column, item)
        font = self.monthly_table.item(total_row, 0).font()
        font.setBold(True)

        for column in range(4):
            self.monthly_table.item(total_row, column).setFont(font)

        table_height = (
            self.monthly_table.horizontalHeader().height()
            + sum(
                self.monthly_table.rowHeight(row)
                for row in range(self.monthly_table.rowCount())
            )
            + self.monthly_table.frameWidth() * 2
        )
        self.monthly_table.setFixedHeight(table_height)
        layout.addWidget(self.monthly_table)
        layout.addStretch()

        self.tabs.addTab(tab, "Monthly Income & Spending")

    def _build_yearly_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Year"))
        self.new_year_selector = QSpinBox()
        self.new_year_selector.setRange(1900, 2200)
        self.new_year_selector.setValue(_current_year())
        toolbar.addWidget(self.new_year_selector)
        add_year = QPushButton("Add Year")
        add_year.clicked.connect(self.add_year)
        toolbar.addWidget(add_year)
        toolbar.addStretch()
        self.yearly_save_button = QPushButton("Save Yearly Log")
        self.yearly_save_button.setObjectName("primary")
        self.yearly_save_button.clicked.connect(self.save_yearly)
        toolbar.addWidget(self.yearly_save_button)
        layout.addLayout(toolbar)
        layout.addSpacing(16)

        self.yearly_table = QTableWidget(0, 7)
        self.yearly_table.setHorizontalHeaderLabels(
            (
                "Year",
                "Current Assets",
                "Investment",
                "Debt",
                "Net Worth",
                "Income",
                "Spending",
            )
        )
        self.yearly_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.yearly_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self.yearly_table.verticalHeader().setVisible(False)
        self.yearly_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.yearly_table.setAlternatingRowColors(True)
        self.yearly_table.itemChanged.connect(self._yearly_cell_changed)
        layout.addWidget(self.yearly_table, 1)
        self.tabs.addTab(tab, "Yearly Log")

    def reload(self) -> None:
        if not self._monthly_dirty:
            self.reload_monthly()
        if not self._yearly_dirty:
            self.reload_yearly()

    def _monthly_year_changed(self, year: int) -> None:
        if self._monthly_dirty:
            choice = QMessageBox.question(
                self,
                "Unsaved monthly records",
                "Save the current year before changing years?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                self.year_selector.blockSignals(True)
                self.year_selector.setValue(self._monthly_loaded_year)
                self.year_selector.blockSignals(False)
                return
            if choice == QMessageBox.StandardButton.Save:
                new_year = year
                self.year_selector.blockSignals(True)
                self.year_selector.setValue(self._monthly_loaded_year)
                self.year_selector.blockSignals(False)
                if not self._persist_monthly(emit=False):
                    self.year_selector.blockSignals(True)
                    self.year_selector.setValue(self._monthly_loaded_year)
                    self.year_selector.blockSignals(False)
                    return
                self.year_selector.blockSignals(True)
                self.year_selector.setValue(new_year)
                self.year_selector.blockSignals(False)
            self._monthly_dirty = False
        self.reload_monthly()

    def reload_monthly(self) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            rows: list[_MonthlyRow] = []
            with self.factory() as session:
                records = list_monthly_records(session, self.year_selector.value())
            rows = [_monthly_row(record) for record in records]
            by_month = {row.month: row for row in rows if 1 <= row.month <= 12}
            for month in range(1, 13):
                row = by_month.get(month)
                income = None if row is None else row.income
                expenditure = None if row is None else row.expenditure
                self._set_monthly_amount(month - 1, 1, income)
                self._set_monthly_amount(month - 1, 2, expenditure)
                self._set_monthly_surplus(month - 1)
            self._update_monthly_summary()
            self._monthly_loaded_year = self.year_selector.value()
            self._monthly_dirty = False
        finally:
            self._loading = False

    def reload_yearly(self) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            with self.factory() as session:
                records = list(list_annual_snapshots(session))
                monthly_records = list(list_monthly_records(session))
            yearly = [_yearly_row(record) for record in records]
            years = {row.year for row in yearly if row.year}
            years.update(_monthly_row(record).year for record in monthly_records)
            years.add(_current_year())
            self._set_yearly_rows(sorted(years))
            for row in yearly:
                index = self._yearly_row_index(row.year)
                if index < 0:
                    continue
                self._set_yearly_amount(index, 1, row.total_asset)
                self._set_yearly_amount(index, 2, row.portfolio_value)
                self._set_yearly_amount(index, 3, row.debt)
            for index in range(self.yearly_table.rowCount()):
                self._update_yearly_calculated(index)
            self._yearly_dirty = False
        finally:
            self._loading = False

    def _set_monthly_amount(self, row: int, column: int, value: int | None) -> None:
        self.monthly_table.item(row, column).setText(_display_amount(value))

    def _set_monthly_surplus(self, row: int) -> None:
        income = _amount(_cell_text(self.monthly_table, row, 1))
        expenditure = _amount(_cell_text(self.monthly_table, row, 2))
        value = None if income is None or expenditure is None else income - expenditure
        item = self.monthly_table.item(row, 3)
        item.setText(_display_amount(value))
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _monthly_cell_changed(self, item: QTableWidgetItem) -> None:
        if (
            self._loading
            or item.row() >= len(MONTH_NAMES) # to exclude the total row
            or item.column() not in (1, 2)
        ):
            return
        self._monthly_dirty = True
        self._set_monthly_surplus(item.row())
        self._update_monthly_summary()

    def _update_monthly_summary(self) -> None:
        incomes = [_amount(_cell_text(self.monthly_table, row, 1)) for row in range(12)]
        expenditures = [_amount(_cell_text(self.monthly_table, row, 2)) for row in range(12)]
        income_values = [value for value in incomes if value is not None]
        expenditure_values = [value for value in expenditures if value is not None]
        # final total row
        total_income = sum(income_values) if income_values else None
        total_expenditure = sum(expenditure_values) if expenditure_values else None
        surplus = (
            None
            if total_income is None or total_expenditure is None
            else total_income - total_expenditure
        )
        self.monthly_table.item(12, 1).setText(_display_amount(total_income))
        self.monthly_table.item(12, 2).setText(_display_amount(total_expenditure))
        self.monthly_table.item(12, 3).setText(_display_amount(surplus))

    def _persist_monthly(self, *, emit: bool) -> bool:
        year = self.year_selector.value()
        parsed: list[_MonthlyRow] = []
        try:
            for row in range(12):
                parsed.append(
                    _MonthlyRow(
                        year,
                        row + 1,
                        _parse_amount(_cell_text(self.monthly_table, row, 1)),
                        _parse_amount(_cell_text(self.monthly_table, row, 2)),
                    )
                )
        except ValueError as error:
            QMessageBox.warning(self, "Monthly records", str(error))
            return False
        try:
            with self.factory.begin() as session:
                for row in parsed:
                    upsert_monthly_record(
                        session,
                        MonthlyFinanceInput(
                            row.year, row.month, row.income, row.expenditure
                        ),
                    )
        except Exception as error:  # noqa: BLE001 - report service/database failures
            QMessageBox.warning(self, "Monthly records", str(error))
            return False
        self._monthly_dirty = False
        self._monthly_loaded_year = year
        self._update_monthly_summary()
        self._refresh_yearly_calculations(year)
        if emit:
            self.data_changed.emit()
        return True

    def save_monthly(self) -> None:
        self._persist_monthly(emit=True)

    def _set_yearly_rows(self, years: Iterable[int]) -> None:
        self.yearly_table.blockSignals(True)
        try:
            self.yearly_table.setRowCount(0)
            for year in years:
                row = self.yearly_table.rowCount()
                self.yearly_table.insertRow(row)
                year_item = QTableWidgetItem(str(year))
                year_item.setFlags(year_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.yearly_table.setItem(row, 0, year_item)
                for column in range(1, 7):
                    item = QTableWidgetItem()
                    if column >= 4:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.yearly_table.setItem(row, column, item)
        finally:
            self.yearly_table.blockSignals(False)

    def add_year(self) -> None:
        year = self.new_year_selector.value()
        if self._yearly_row_index(year) >= 0:
            self.yearly_table.setCurrentCell(self._yearly_row_index(year), 1)
            return
        insert_at = self.yearly_table.rowCount()
        for row in range(self.yearly_table.rowCount()):
            if int(_cell_text(self.yearly_table, row, 0)) > year:
                insert_at = row
                break
        self._insert_yearly_row(insert_at, year)
        self._yearly_dirty = True
        self.yearly_table.setCurrentCell(insert_at, 1)

    def _insert_yearly_row(self, row: int, year: int) -> None:
        self.yearly_table.blockSignals(True)
        try:
            self.yearly_table.insertRow(row)
            year_item = QTableWidgetItem(str(year))
            year_item.setFlags(year_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.yearly_table.setItem(row, 0, year_item)
            for column in range(1, 7):
                item = QTableWidgetItem()
                if column >= 4:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.yearly_table.setItem(row, column, item)
        finally:
            self.yearly_table.blockSignals(False)

    def _yearly_row_index(self, year: int) -> int:
        for row in range(self.yearly_table.rowCount()):
            if _cell_text(self.yearly_table, row, 0) == str(year):
                return row
        return -1

    def _set_yearly_amount(self, row: int, column: int, value: int | None) -> None:
        self.yearly_table.item(row, column).setText(_display_amount(value))

    def _yearly_cell_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() not in (1, 2, 3):
            return
        self._yearly_dirty = True
        self._update_yearly_calculated(item.row())

    def _update_yearly_calculated(self, row: int) -> None:
        values = [_amount(_cell_text(self.yearly_table, row, column)) for column in (1, 2, 3)]
        net_worth = None if any(value is None for value in values) else values[0] + values[1] - values[2]
        self.yearly_table.item(row, 4).setText(_display_amount(net_worth))
        year = int(_cell_text(self.yearly_table, row, 0) or 0)
        income, expenditure = self._annual_totals(year)
        self.yearly_table.item(row, 5).setText(_display_amount(income))
        self.yearly_table.item(row, 6).setText(_display_amount(expenditure))

    def _annual_totals(self, year: int) -> tuple[int | None, int | None]:
        with self.factory() as session:
            summary = calculate_yearly_summary(session, year)
        return (
            summary.income,
            summary.expenditure
        )

    def save_yearly(self) -> None:
        parsed: list[_YearlyRow] = []
        try:
            for row in range(self.yearly_table.rowCount()):
                parsed.append(
                    _YearlyRow(
                        int(_cell_text(self.yearly_table, row, 0)),
                        _parse_amount(_cell_text(self.yearly_table, row, 1)),
                        _parse_amount(_cell_text(self.yearly_table, row, 2)),
                        _parse_amount(_cell_text(self.yearly_table, row, 3)),
                    )
                )
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Yearly log", str(error))
            return
        try:
            with self.factory.begin() as session:
                for row in parsed:
                    upsert_annual_snapshot(
                        session,
                        AnnualFinanceInput(
                            row.year,
                            row.total_asset,
                            row.portfolio_value,
                            row.debt,
                        ),
                    )
        except Exception as error:  # noqa: BLE001 - report service/database failures
            QMessageBox.warning(self, "Yearly log", str(error))
            return
        for row in range(self.yearly_table.rowCount()):
            self._update_yearly_calculated(row)
        self._yearly_dirty = False
        self.data_changed.emit()

    def _refresh_yearly_calculations(self, year: int) -> None:
        row = self._yearly_row_index(year)
        if row < 0:
            row = self.yearly_table.rowCount()
            self._insert_yearly_row(row, year)
        self._update_yearly_calculated(row)


__all__ = ["PersonalFinanceView"]
