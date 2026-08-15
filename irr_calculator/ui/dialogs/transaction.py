from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QMessageBox, QVBoxLayout,
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
        self.trade_date.setMaximumDate(QDate.currentDate())
        self.shares = self._number(signed=True)
        self.cash = self._number(signed=True)
        self.trade = self._number()
        self.income = self._number()
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
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    @staticmethod
    def _number(signed: bool = False) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setDecimals(0)
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
        self.shares.setValue(row.shares_delta)
        self.cash.setValue(row.external_cash_flow)
        self.trade.setValue(row.trade_amount)
        self.income.setValue(row.income_amount)

    def accept(self) -> None:
        qdate = self.trade_date.date()
        try:
            self.result_data = validate(TransactionInput(
                portfolio_id=self.portfolio.currentData(), security_id=self.security.currentData(),
                kind=self.kind.currentData(), trade_date=date(qdate.year(), qdate.month(), qdate.day()),
                shares_delta=int(self.shares.value()), external_cash_flow=int(self.cash.value()),
                trade_amount=int(self.trade.value()), income_amount=int(self.income.value()),
                source_key=self.transaction.source_key,
            ))
        except Exception as error:
            QMessageBox.warning(self, "Transaction not valid", str(error))
            return
        super().accept()
