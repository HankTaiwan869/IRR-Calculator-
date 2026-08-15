from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ...models import Portfolio
from ...services.analytics import portfolio_summary


def money(value: int | None) -> str:
    return "Not calculable" if value is None else f"NT$ {value:,}"


class MetricCard(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        self.value = QLabel("—")
        self.value.setObjectName("metricValue")
        label = QLabel(title)
        label.setObjectName("muted")
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.value)


class DashboardView(QScrollArea):
    refresh_requested = pyqtSignal(object, bool)

    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.setWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(4, 4, 12, 24)
        layout.setSpacing(14)

        bar = QHBoxLayout()
        self.portfolio = QComboBox()
        self.portfolio.currentIndexChanged.connect(self.reload)
        refresh = QPushButton("Refresh Prices")
        refresh.setObjectName("primary")
        refresh.clicked.connect(
            lambda: self.refresh_requested.emit(self.portfolio.currentData(), False)
        )
        retry = QPushButton("Retry Prices")
        retry.setToolTip("Explicitly bypass the current daily refresh cache")
        retry.clicked.connect(
            lambda: self.refresh_requested.emit(self.portfolio.currentData(), True)
        )
        bar.addWidget(QLabel("Portfolio"))
        bar.addWidget(self.portfolio, 1)
        bar.addStretch()
        bar.addWidget(retry)
        bar.addWidget(refresh)
        layout.addLayout(bar)

        grid = QGridLayout()
        names = (
            "Total assets",
            "Total profit",
            "Realized profit",
            "Unrealized profit",
            "Dividend income",
            "Annual / monthly IRR",
        )
        self.cards = {name: MetricCard(name) for name in names}
        for index, card in enumerate(self.cards.values()):
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)

        layout.addStretch()
        self.reload_portfolios()

    def reload_portfolios(self) -> None:
        selected = self.portfolio.currentData()
        with self.factory() as session:
            portfolios = list(
                session.scalars(
                    select(Portfolio)
                    .where(Portfolio.archived_at.is_(None))
                    .order_by(Portfolio.name)
                )
            )
        self.portfolio.blockSignals(True)
        self.portfolio.clear()
        self.portfolio.addItem("All portfolios", None)
        for item in portfolios:
            self.portfolio.addItem(item.name, item.id)
        index = self.portfolio.findData(selected)
        self.portfolio.setCurrentIndex(max(index, 0))
        self.portfolio.blockSignals(False)
        self.reload()

    def reload(self) -> None:
        if self.portfolio.count() == 0:
            return
        with self.factory() as session:
            summary = portfolio_summary(
                session,
                datetime.now().astimezone().date(),
                self.portfolio.currentData(),
            )
        self.cards["Total assets"].value.setText(money(summary.total_assets))
        self.cards["Total profit"].value.setText(money(summary.total_profit))
        self.cards["Realized profit"].value.setText(money(summary.realized_profit))
        self.cards["Unrealized profit"].value.setText(money(summary.unrealized_profit))
        self.cards["Dividend income"].value.setText(money(summary.dividend_income))
        irr = (
            "Not calculable"
            if summary.annual_irr is None
            else f"{summary.annual_irr:.2%} / {summary.monthly_irr:.2%}"
        )
        self.cards["Annual / monthly IRR"].value.setText(irr)
