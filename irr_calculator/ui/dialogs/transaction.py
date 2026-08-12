from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QMessageBox, QVBoxLayout,
)
from sqlalchemy import select

from ...models import Portfolio, Security, Transaction, TransactionKind
from ...services.transactions import TransactionInput, validate


class TransactionDialog(QDialog):
    def __init__(self, session_factory, transaction: Transaction, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        self.transaction = transaction
        self.result_data: TransactionInput | None = None
        self.setWindowTitle("Edit Transaction")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.portfolio = QComboBox()
        self.security = QComboBox()
        self.kind = QComboBox()
        self.trade_date = QDateEdit()
        self.trade_date.setCalendarPopup(True)
        self.shares = self._number(8, signed=True)
        self.cash = self._number(2, signed=True)
        self.trade = self._number(2)
        self.income = self._number(2)
        self.price = self._number(4)
        self.fees = self._number(2)
        self.notes = QLineEdit()
        with self.factory() as session:
            portfolios = list(session.scalars(select(Portfolio).order_by(Portfolio.name)))
            securities = list(session.scalars(select(Security).order_by(Security.symbol)))
        for item in portfolios:
            self.portfolio.addItem(item.name, item.id)
        self.security.addItem("None", None)
        for item in securities:
            self.security.addItem(f"{item.symbol}  {item.name_zh}", item.id)
        for kind in TransactionKind:
            self.kind.addItem(kind.value.replace("_", " ").title(), kind)
        for label, widget in (
            ("Portfolio", self.portfolio), ("Security", self.security), ("Activity", self.kind),
            ("Date", self.trade_date), ("Signed shares", self.shares), ("External cash", self.cash),
            ("Trade amount", self.trade), ("Dividend income", self.income),
            ("Unit price", self.price), ("Fees", self.fees), ("Notes", self.notes),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    @staticmethod
    def _number(decimals: int, signed: bool = False) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setMaximum(999_999_999_999)
        if signed:
            widget.setMinimum(-999_999_999_999)
        return widget

    def _populate(self) -> None:
        row = self.transaction
        self.portfolio.setCurrentIndex(self.portfolio.findData(row.portfolio_id))
        self.security.setCurrentIndex(self.security.findData(row.security_id))
        self.kind.setCurrentIndex(self.kind.findData(TransactionKind(row.kind)))
        self.trade_date.setDate(QDate(row.trade_date.year, row.trade_date.month, row.trade_date.day))
        self.shares.setValue(float(row.shares_delta))
        self.cash.setValue(float(row.external_cash_flow))
        self.trade.setValue(float(row.trade_amount))
        self.income.setValue(float(row.income_amount))
        self.price.setValue(float(row.unit_price or 0))
        self.fees.setValue(float(row.fees))
        self.notes.setText(row.notes)

    def accept(self) -> None:
        qdate = self.trade_date.date()
        try:
            self.result_data = validate(TransactionInput(
                portfolio_id=self.portfolio.currentData(), security_id=self.security.currentData(),
                kind=self.kind.currentData(), trade_date=date(qdate.year(), qdate.month(), qdate.day()),
                shares_delta=Decimal(str(self.shares.value())), external_cash_flow=Decimal(str(self.cash.value())),
                trade_amount=Decimal(str(self.trade.value())), income_amount=Decimal(str(self.income.value())),
                unit_price=Decimal(str(self.price.value())) if self.price.value() else None,
                fees=Decimal(str(self.fees.value())), notes=self.notes.text(), source_key=self.transaction.source_key,
            ))
        except Exception as error:
            QMessageBox.warning(self, "Transaction not valid", str(error))
            return
        super().accept()
