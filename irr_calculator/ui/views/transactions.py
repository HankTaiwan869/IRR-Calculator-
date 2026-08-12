from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt6.QtCore import QDate, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
from sqlalchemy import select

from ...exceptions import ValidationError
from ...models import Portfolio, Security, TransactionKind
from ...services.transactions import TransactionInput, create_transaction


class TransactionsView(QWidget):
    saved = pyqtSignal()

    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 12, 20)

        context = QGroupBox("Transaction context")
        context_form = QFormLayout(context)
        self.portfolio = QComboBox()
        self.security = QComboBox()
        self.security.setEditable(True)
        self.security.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self._run_security_search)
        self.security.lineEdit().textEdited.connect(self._schedule_security_search)
        self.exchange = QComboBox()
        self.exchange.addItems(("All exchanges", "twse", "tpex", "emerging"))
        self.security_type = QComboBox()
        self.security_type.addItems(("All types", "stock", "etf"))
        self.exchange.currentIndexChanged.connect(lambda: self._filter_securities(""))
        self.security_type.currentIndexChanged.connect(lambda: self._filter_securities(""))
        self.kind = QComboBox()
        for kind in TransactionKind:
            if kind is not TransactionKind.LEGACY_CASH_FLOW:
                self.kind.addItem(kind.value.replace("_", " ").title(), kind)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.trade_date = QDateEdit(QDate.currentDate())
        self.trade_date.setCalendarPopup(True)
        context_form.addRow("Portfolio", self.portfolio)
        context_form.addRow("Security", self.security)
        context_form.addRow("Exchange", self.exchange)
        context_form.addRow("Security type", self.security_type)
        context_form.addRow("Activity", self.kind)
        context_form.addRow("Trade date", self.trade_date)
        layout.addWidget(context)

        values = QGroupBox("Accounting details")
        form = QFormLayout(values)
        self.shares = self._number(8)
        self.trade_amount = self._number(2)
        self.cash_flow = self._signed_number(2)
        self.income = self._number(2)
        self.fees = self._number(2)
        self.unit_price = self._number(4)
        self.notes = QLineEdit()
        form.addRow("Signed shares", self.shares)
        form.addRow("Trade amount", self.trade_amount)
        form.addRow("External cash flow", self.cash_flow)
        form.addRow("Dividend income", self.income)
        form.addRow("Unit price (optional)", self.unit_price)
        form.addRow("Fees", self.fees)
        form.addRow("Notes", self.notes)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setObjectName("muted")
        form.addRow(self.help)
        layout.addWidget(values)

        actions = QHBoxLayout()
        actions.addStretch()
        save = QPushButton("Save Transaction")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        actions.addWidget(save)
        layout.addLayout(actions)
        layout.addStretch()
        self.reload_context()
        self._kind_changed()

    @staticmethod
    def _number(decimals: int) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setMaximum(999_999_999_999)
        return widget

    @classmethod
    def _signed_number(cls, decimals: int) -> QDoubleSpinBox:
        widget = cls._number(decimals)
        widget.setMinimum(-999_999_999_999)
        return widget

    def reload_context(self) -> None:
        selected_portfolio = self.portfolio.currentData()
        with self.factory() as session:
            portfolios = list(session.scalars(select(Portfolio).where(Portfolio.archived_at.is_(None)).order_by(Portfolio.name)))
        self.portfolio.clear()
        for item in portfolios:
            self.portfolio.addItem(item.name, item.id)
        self.portfolio.setCurrentIndex(max(self.portfolio.findData(selected_portfolio), 0))
        self._filter_securities("")

    def _schedule_security_search(self, _text: str) -> None:
        self.search_timer.start()

    def _run_security_search(self) -> None:
        self._filter_securities(self.security.currentText())

    def _filter_securities(self, text: str) -> None:
        from ...services.securities import search_securities
        selected = self.security.currentData()
        with self.factory() as session:
            records = search_securities(
                session, text,
                exchange=self.exchange.currentText() if self.exchange.currentIndex() else None,
                security_type=self.security_type.currentText() if self.security_type.currentIndex() else None,
                limit=50,
            )
        self.security.blockSignals(True)
        self.security.clear()
        for item in records:
            self.security.addItem(f"{item.symbol}  {item.name_zh}", item.id)
        index = self.security.findData(selected)
        if index >= 0:
            self.security.setCurrentIndex(index)
        elif text:
            self.security.setEditText(text)
        self.security.blockSignals(False)

    def _kind_changed(self) -> None:
        kind = self.kind.currentData()
        reinvested = kind is TransactionKind.REINVESTED_DIVIDEND
        dividend = kind is TransactionKind.DIVIDEND
        opening = kind is TransactionKind.OPENING_POSITION
        self.help.setText(
            "Fully reinvested dividends normally have zero external cash flow; any difference must be entered as a paid remainder (+) or owner top-up (-)."
            if reinvested else
            "Opening positions reconcile existing shares with zero external cash. Total cost is optional; omitting it marks cost basis incomplete."
            if opening else
            "Buys use positive shares and negative cash. Sells use negative shares and positive cash."
        )
        self.income.setEnabled(reinvested or dividend)
        self.trade_amount.setEnabled(not dividend)
        self.shares.setEnabled(not dividend)
        self.cash_flow.setEnabled(not opening)
        self.fees.setEnabled(not opening and not dividend)

    def save(self) -> None:
        if self.portfolio.currentData() is None or self.security.currentData() is None:
            QMessageBox.warning(self, "Transaction", "Choose a portfolio and security. Sync the security master first if needed.")
            return
        qdate = self.trade_date.date()
        data = TransactionInput(
            portfolio_id=self.portfolio.currentData(), security_id=self.security.currentData(),
            kind=self.kind.currentData(), trade_date=date(qdate.year(), qdate.month(), qdate.day()),
            shares_delta=Decimal(str(self.shares.value())), external_cash_flow=Decimal(str(self.cash_flow.value())),
            trade_amount=Decimal(str(self.trade_amount.value())), income_amount=Decimal(str(self.income.value())),
            unit_price=Decimal(str(self.unit_price.value())) if self.unit_price.value() else None,
            fees=Decimal(str(self.fees.value())), notes=self.notes.text(),
        )
        try:
            with self.factory.begin() as session:
                create_transaction(session, data)
        except (ValidationError, Exception) as error:
            QMessageBox.warning(self, "Transaction not saved", str(error))
            return
        QMessageBox.information(self, "Transaction", "Transaction saved.")
        self.saved.emit()
