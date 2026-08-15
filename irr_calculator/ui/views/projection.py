from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QLabel, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)
from sqlalchemy import select

from ...models import Portfolio
from ...services.analytics import portfolio_summary, projection


class ProjectionView(QScrollArea):
    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.setWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(4, 4, 12, 24)
        layout.setSpacing(16)

        controls = QGridLayout()
        controls.setHorizontalSpacing(16)
        controls.setVerticalSpacing(12)
        self.portfolio = QComboBox()
        self.portfolio.currentIndexChanged.connect(self.reload)
        controls.addWidget(QLabel("Portfolio"), 0, 0)
        controls.addWidget(self.portfolio, 0, 1, 1, 3)

        self.years = QSpinBox()
        self.years.setRange(0, 100)
        self.years.setSingleStep(1)
        self.years.setValue(30)
        self.years.setKeyboardTracking(False)
        self.years.setToolTip("Projection length from 0 to 100 years")
        controls.addWidget(QLabel("Years"), 1, 0)
        controls.addWidget(self.years, 1, 1)

        self.rates: list[QDoubleSpinBox] = []
        for row, (label, value) in enumerate(
            (("Conservative %", 6.5), ("Expected %", 9.0), ("Optimistic %", 11.5)),
            start=2,
        ):
            control = QDoubleSpinBox()
            control.setRange(-99.0, 100.0)
            control.setDecimals(2)
            control.setValue(value)
            control.setSuffix("%")
            control.setKeyboardTracking(False)
            self.rates.append(control)
            controls.addWidget(QLabel(label), row, 0)
            controls.addWidget(control, row, 1)
        controls.setColumnStretch(1, 1)
        controls.setColumnStretch(3, 1)
        layout.addLayout(controls)

        self.chart_placeholder = QLabel("The projection chart loads when this tab is opened.")
        self.chart_placeholder.setObjectName("muted")
        self.chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_placeholder.setMinimumHeight(360)
        layout.addWidget(self.chart_placeholder, 1)
        self.chart = None

        self.years.valueChanged.connect(self.reload)
        for control in self.rates:
            control.valueChanged.connect(self.reload)
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
        self.portfolio.setCurrentIndex(max(self.portfolio.findData(selected), 0))
        self.portfolio.blockSignals(False)
        self.reload()

    def ensure_chart(self) -> None:
        if self.chart is not None:
            return
        import plotly
        self.chart = QWebEngineView()
        plotly_dir = Path(plotly.__file__).resolve().parent / "package_data"
        self._plotly_base_url = QUrl.fromLocalFile(f"{plotly_dir}/")
        layout = self.content.layout()
        layout.replaceWidget(self.chart_placeholder, self.chart)
        self.chart_placeholder.deleteLater()
        self.reload()

    def reload(self) -> None:
        if self.portfolio.count() == 0 or self.chart is None:
            return
        with self.factory() as session:
            summary = portfolio_summary(session, date.today(), self.portfolio.currentData())

        import plotly.graph_objects as go
        import plotly.io as pio

        figure = go.Figure()
        rates = tuple(control.value() / 100 for control in self.rates)
        scenarios = projection(summary.total_assets, self.years.value(), rates)
        if scenarios is None:
            figure.add_annotation(
                text="Projection unavailable until all open holdings have prices.",
                x=.5, y=.5, xref="paper", yref="paper", showarrow=False,
            )
            figure.update_xaxes(visible=False)
            figure.update_yaxes(visible=False)
        else:
            labels = tuple(f"{control.value():g}%" for control in self.rates)
            for values, label in zip(scenarios, labels, strict=True):
                figure.add_scatter(
                    x=list(range(len(values))), y=values, mode="lines", name=label,
                    hovertemplate="Year %{x}<br>NT$ %{y:,.0f}<extra>%{fullData.name}</extra>",
                )
            figure.update_xaxes(title_text="Year", dtick=5 if self.years.value() >= 20 else 1)
            figure.update_yaxes(title_text="TWD", tickformat=",.0f")
        figure.update_layout(
            template="plotly_white",
            margin=dict(l=70, r=30, t=30, b=60),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        html = pio.to_html(
            figure,
            full_html=True,
            include_plotlyjs=False,
            config={"displaylogo": False, "responsive": True},
        ).replace("</head>", '<script src="plotly.min.js"></script></head>')
        self.chart.setHtml(html, self._plotly_base_url)
