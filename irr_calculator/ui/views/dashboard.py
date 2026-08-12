from __future__ import annotations

from datetime import date
from decimal import Decimal

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)
from sqlalchemy import select

from ...models import Portfolio
from ...services.analytics import portfolio_summary, projection


def money(value: Decimal | None) -> str:
    return "Not calculable" if value is None else f"NT$ {value:,.0f}"


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
        refresh.clicked.connect(lambda: self.refresh_requested.emit(self.portfolio.currentData(), False))
        retry = QPushButton("Retry Prices")
        retry.setToolTip("Explicitly bypass the current daily refresh cache")
        retry.clicked.connect(lambda: self.refresh_requested.emit(self.portfolio.currentData(), True))
        bar.addWidget(QLabel("Portfolio"))
        bar.addWidget(self.portfolio, 1)
        bar.addStretch()
        bar.addWidget(retry)
        bar.addWidget(refresh)
        layout.addLayout(bar)

        grid = QGridLayout()
        names = ("Total assets", "Total profit", "Realized profit", "Unrealized profit", "Dividend income", "Annual / monthly IRR")
        self.cards = {name: MetricCard(name) for name in names}
        for index, card in enumerate(self.cards.values()):
            grid.addWidget(card, index // 2, index % 2)
        layout.addLayout(grid)

        title = QLabel("30-year projection")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        controls = QGridLayout()
        self.years = QSpinBox()
        self.years.setRange(1, 30)
        self.years.setValue(30)
        self.rates: list[QDoubleSpinBox] = []
        controls.addWidget(QLabel("Years"), 0, 0)
        controls.addWidget(self.years, 0, 1)
        for index, (label, value) in enumerate((("Conservative %", 6.5), ("Expected %", 9.0), ("Optimistic %", 11.5)), start=1):
            control = QDoubleSpinBox()
            control.setRange(-99.0, 100.0)
            control.setDecimals(2)
            control.setValue(value)
            control.setSuffix("%")
            self.rates.append(control)
            pair = index
            controls.addWidget(QLabel(label), pair // 2, (pair % 2) * 2)
            controls.addWidget(control, pair // 2, (pair % 2) * 2 + 1)
        controls.setColumnStretch(1, 1)
        controls.setColumnStretch(3, 1)
        layout.addLayout(controls)
        self.chart_placeholder = QLabel("Projection chart loads when the Dashboard is first opened.")
        self.chart_placeholder.setObjectName("muted")
        self.chart_placeholder.setMinimumHeight(240)
        layout.addWidget(self.chart_placeholder)
        layout.addStretch()
        self.chart = None
        self.years.valueChanged.connect(self.reload)
        for control in self.rates:
            control.valueChanged.connect(self.reload)
        self.reload_portfolios()

    def reload_portfolios(self) -> None:
        selected = self.portfolio.currentData()
        with self.factory() as session:
            portfolios = list(session.scalars(select(Portfolio).where(Portfolio.archived_at.is_(None)).order_by(Portfolio.name)))
        self.portfolio.blockSignals(True)
        self.portfolio.clear()
        self.portfolio.addItem("All portfolios", None)
        for item in portfolios:
            self.portfolio.addItem(item.name, item.id)
        index = self.portfolio.findData(selected)
        self.portfolio.setCurrentIndex(max(index, 0))
        self.portfolio.blockSignals(False)
        self.reload()

    def ensure_chart(self) -> None:
        if self.chart is not None:
            return
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self.chart = FigureCanvasQTAgg(Figure(figsize=(7, 3), tight_layout=True))
        layout = self.content.layout()
        layout.replaceWidget(self.chart_placeholder, self.chart)
        self.chart_placeholder.deleteLater()
        self.reload()

    def reload(self) -> None:
        if self.portfolio.count() == 0:
            return
        with self.factory() as session:
            summary = portfolio_summary(session, date.today(), self.portfolio.currentData())
        self.cards["Total assets"].value.setText(money(summary.total_assets))
        self.cards["Total profit"].value.setText(money(summary.total_profit))
        self.cards["Realized profit"].value.setText(money(summary.realized_profit))
        self.cards["Unrealized profit"].value.setText(money(summary.unrealized_profit))
        self.cards["Dividend income"].value.setText(money(summary.dividend_income))
        irr = "Not calculable" if summary.annual_irr is None else f"{summary.annual_irr:.2%} / {summary.monthly_irr:.2%}"
        self.cards["Annual / monthly IRR"].value.setText(irr)
        if self.chart is not None:
            figure = self.chart.figure
            figure.clear()
            axes = figure.add_subplot(111)
            rates = tuple(Decimal(str(control.value() / 100)) for control in self.rates)
            scenarios = projection(summary.total_assets, self.years.value(), rates)
            labels = tuple(f"{control.value():g}%" for control in self.rates)
            for values, label in zip(scenarios, labels, strict=True):
                axes.plot(range(len(values)), [float(item) for item in values], label=label)
            axes.set_xlabel("Year")
            axes.set_ylabel("TWD")
            axes.grid(alpha=.2)
            axes.legend()
            self.chart.draw_idle()
