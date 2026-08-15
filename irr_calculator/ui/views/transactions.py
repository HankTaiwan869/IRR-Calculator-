from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ...models import Portfolio, Security, TransactionKind
from ...services.transactions import TransactionInput, create_transaction


class TransactionsView(QScrollArea):
    saved = pyqtSignal()

    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.setWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(4, 4, 12, 24)
        layout.setSpacing(18)

        context = QGroupBox("Transaction context")
        context_form = QFormLayout(context)
        self.portfolio = QComboBox()
        self.security = QLineEdit()
        self.security.setPlaceholderText("Enter an exact symbol, for example 00692")
        self.kind = QComboBox()
        for kind in TransactionKind:
            if kind is not TransactionKind.LEGACY_CASH_FLOW:
                self.kind.addItem(kind.value.replace("_", " ").title(), kind)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.trade_date = QDateEdit(QDate.currentDate())
        self.trade_date.setCalendarPopup(True)
        self.trade_date.setMaximumDate(QDate.currentDate())
        context_form.addRow("Portfolio", self.portfolio)
        context_form.addRow("Security", self.security)
        context_form.addRow("Activity", self.kind)
        context_form.addRow("Trade date", self.trade_date)
        layout.addWidget(context)

        values = QGroupBox("Accounting details")
        form = QFormLayout(values)
        form.setContentsMargins(18, 30, 18, 22)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)
        self.shares = self._number()
        self.trade_amount = self._number()
        self.cash_flow = self._signed_number()
        self.income = self._number()
        form.addRow("Signed shares", self.shares)
        form.addRow("Trade amount", self.trade_amount)
        form.addRow("External cash flow", self.cash_flow)
        form.addRow("Dividend income", self.income)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setObjectName("muted")
        self.help.setMinimumHeight(48)
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
    def _number() -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setDecimals(0)
        widget.setMaximum(999_999_999_999)
        widget.setMinimumHeight(42)
        return widget

    @classmethod
    def _signed_number(cls) -> QDoubleSpinBox:
        widget = cls._number()
        widget.setMinimum(-999_999_999_999)
        return widget

    def reload_context(self) -> None:
        selected_portfolio = self.portfolio.currentData()
        with self.factory() as session:
            portfolios = list(
                session.scalars(
                    select(Portfolio)
                    .where(Portfolio.archived_at.is_(None))
                    .order_by(Portfolio.name)
                )
            )
        self.portfolio.clear()
        for item in portfolios:
            self.portfolio.addItem(item.name, item.id)
        self.portfolio.setCurrentIndex(
            max(self.portfolio.findData(selected_portfolio), 0)
        )

    def _kind_changed(self) -> None:
        kind = self.kind.currentData()
        reinvested = kind is TransactionKind.REINVESTED_DIVIDEND
        dividend = kind is TransactionKind.DIVIDEND
        opening = kind is TransactionKind.OPENING_POSITION
        self.help.setText(
            "Fully reinvested dividends normally have zero external cash flow; any difference must be entered as a paid remainder (+) or owner top-up (-)."
            if reinvested
            else "Opening positions reconcile existing shares with zero external cash. Total cost is optional; omitting it marks cost basis incomplete."
            if opening
            else "Buys use positive shares and negative cash. Sells use negative shares and positive cash."
        )
        self._set_applicable(self.income, reinvested or dividend)
        self._set_applicable(self.trade_amount, not dividend)
        self._set_applicable(self.shares, not dividend)
        self._set_applicable(self.cash_flow, not opening)

    @staticmethod
    def _set_applicable(widget: QDoubleSpinBox, applicable: bool) -> None:
        """Disable and clear values that cannot apply to the selected activity."""
        widget.setEnabled(applicable)
        if not applicable:
            widget.setValue(0)

    def save(self) -> None:
        portfolio_id = self.portfolio.currentData()
        symbol = self.security.text().strip()
        if portfolio_id is None or not symbol:
            QMessageBox.warning(
                self, "Transaction", "Choose a portfolio and enter a security symbol."
            )
            return
        with self.factory() as session:
            security_id = session.scalar(
                select(Security.id)
                .where(Security.symbol == symbol, Security.active.is_(True))
                .order_by((Security.provider == "FinMind").desc(), Security.id)
                .limit(1)
            )
        if security_id is None:
            QMessageBox.warning(
                self,
                "Transaction",
                f'No active security has the exact symbol "{symbol}". Sync the security master first if needed.',
            )
            return
        qdate = self.trade_date.date()
        data = TransactionInput(
            portfolio_id=portfolio_id,
            security_id=security_id,
            kind=self.kind.currentData(),
            trade_date=date(qdate.year(), qdate.month(), qdate.day()),
            shares_delta=int(self.shares.value()),
            external_cash_flow=int(self.cash_flow.value()),
            trade_amount=int(self.trade_amount.value()),
            income_amount=int(self.income.value()),
        )
        try:
            with self.factory.begin() as session:
                create_transaction(session, data)
        except Exception as error:  # noqa: BLE001 - report database and validation failures in the UI
            QMessageBox.warning(self, "Transaction not saved", str(error))
            return
        QMessageBox.information(self, "Transaction", "Transaction saved.")
        self.saved.emit()
