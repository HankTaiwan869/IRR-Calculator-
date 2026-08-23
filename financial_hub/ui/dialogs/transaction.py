from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)
from sqlalchemy import select

from ...exceptions import ValidationError
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
        self.shares = self._number()
        self.amount = self._number()
        with self.factory() as session:
            portfolios = list(
                session.scalars(select(Portfolio).order_by(Portfolio.name))
            )
            securities = list(
                session.scalars(select(Security).order_by(Security.symbol))
            )
        for item in portfolios:
            self.portfolio.addItem(item.name, item.id)
        self.security.addItem("None", None)
        for item in securities:
            self.security.addItem(f"{item.symbol}  {item.name_zh}", item.id)
        for kind in TransactionKind:
            self.kind.addItem(kind.value.replace("_", " ").title(), kind)
        for label, widget in (
            ("Portfolio", self.portfolio),
            ("Security", self.security),
            ("Activity", self.kind),
            ("Date", self.trade_date),
            ("Shares", self.shares),
            ("Amount", self.amount),
        ):
            form.addRow(label, widget)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setObjectName("muted")
        form.addRow(self.help)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    @staticmethod
    def _number() -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setDecimals(0)
        widget.setMaximum(999_999_999_999)
        widget.setMinimum(0)
        widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        return widget

    def _populate(self) -> None:
        row = self.transaction
        self.portfolio.setCurrentIndex(self.portfolio.findData(row.portfolio_id))
        self.security.setCurrentIndex(self.security.findData(row.security_id))
        self.kind.setCurrentIndex(self.kind.findData(TransactionKind(row.kind)))
        self.trade_date.setDate(
            QDate(row.trade_date.year, row.trade_date.month, row.trade_date.day)
        )
        kind = TransactionKind(row.kind)
        # Regular activities display unsigned values; legacy imported cash
        # flows retain their signed amount because direction is not inferable.
        self.shares.setValue(abs(row.shares_delta))
        self.amount.setValue(
            row.amount if kind is TransactionKind.LEGACY_CASH_FLOW else abs(row.amount)
        )
        self._kind_changed()

    def _kind_changed(self) -> None:
        kind = self.kind.currentData()
        reinvested = kind is TransactionKind.REINVESTED_DIVIDEND
        reconciliation = kind is TransactionKind.POSITION_RECONCILIATION
        dividend = kind is TransactionKind.DIVIDEND
        opening = kind is TransactionKind.OPENING_POSITION
        legacy = kind is TransactionKind.LEGACY_CASH_FLOW
        self.amount.setMinimum(-999_999_999_999 if legacy else 0)
        self.help.setText(
            "A reinvested dividend adds shares with zero owner cash flow and does not count as dividend income."
            if reinvested
            else "A position reconciliation adds legacy shares with zero owner cash flow and does not establish a cost basis."
            if reconciliation
            else "Enter the paid dividend amount; it is included in total dividend income."
            if dividend
            else "An opening position adds existing shares; enter the initial or deemed investment amount."
            if opening
            else "A legacy cash flow uses zero shares and a nonzero signed amount."
            if legacy
            else "Buys add shares and deduct the amount. Sells remove shares and add the amount."
        )
        self._set_applicable(self.shares, not (dividend or legacy))
        self._set_applicable(self.amount, not (reinvested or reconciliation))

    @staticmethod
    def _set_applicable(widget: QDoubleSpinBox, applicable: bool) -> None:
        widget.setEnabled(applicable)
        if not applicable:
            widget.setValue(0)

    def accept(self) -> None:
        qdate = self.trade_date.date()
        kind = self.kind.currentData()
        shares, amount = self._signed_values(
            kind, int(self.shares.value()), int(self.amount.value())
        )
        try:
            self.result_data = validate(
                TransactionInput(
                    portfolio_id=self.portfolio.currentData(),
                    security_id=self.security.currentData(),
                    kind=kind,
                    trade_date=date(qdate.year(), qdate.month(), qdate.day()),
                    shares_delta=shares,
                    amount=amount,
                )
            )
        except ValidationError as error:
            QMessageBox.warning(self, "Transaction not valid", str(error))
            return
        super().accept()

    @staticmethod
    def _signed_values(
        kind: TransactionKind, shares: int, amount: int
    ) -> tuple[int, int]:
        """Convert form values to the signed transaction ledger convention."""
        if kind is TransactionKind.BUY:
            return shares, -amount
        if kind is TransactionKind.SELL:
            return -shares, amount
        if kind is TransactionKind.DIVIDEND:
            return 0, amount
        if kind is TransactionKind.REINVESTED_DIVIDEND:
            return shares, 0
        if kind is TransactionKind.POSITION_RECONCILIATION:
            return shares, 0
        if kind is TransactionKind.OPENING_POSITION:
            return shares, -amount
        # Imported legacy cash flows must preserve their original direction.
        return 0, amount
