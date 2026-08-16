from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QThreadPool, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..preferences import get_finmind_token
from ..providers import FinMindProvider
from ..services.quotes import refresh_prices
from .views import (
    DashboardView,
    HistoryView,
    PortfoliosView,
    ProjectionView,
    SettingsView,
    TransactionsView,
)
from .workers import FunctionWorker


class MainWindow(QMainWindow):
    PAGE_NAMES = (
        "Dashboard",
        "Projection",
        "Transactions",
        "Portfolios",
        "History",
        "Settings",
    )

    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        self.pool = QThreadPool.globalInstance()
        self.setWindowTitle("Financial Hub")
        self.resize(1240, 800)
        self.setMinimumSize(900, 620)
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 12, 12, 18)
        brand = QLabel("Financial Hub")
        brand.setObjectName("brand")
        side_layout.addWidget(brand)
        self.nav_buttons: list[QPushButton] = []
        for index, name in enumerate(self.PAGE_NAMES):
            button = QPushButton(name)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, page=index: self.show_page(page)
            )
            self.nav_buttons.append(button)
            side_layout.addWidget(button)
        side_layout.addStretch()
        self.version_label = QLabel(f"Version {__version__}")
        self.version_label.setStyleSheet("color: #8fa0ba; padding: 8px;")
        side_layout.addWidget(self.version_label)
        outer.addWidget(sidebar)

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(28, 22, 24, 16)
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        header.addWidget(self.title)
        header.addStretch()
        main_layout.addLayout(header)
        self.stack = QStackedWidget()
        self.dashboard = DashboardView(self.factory)
        self.projection = ProjectionView(self.factory)
        self.transactions = TransactionsView(self.factory)
        self.history = HistoryView(self.factory)
        self.portfolios = PortfoliosView(self.factory)
        self.settings = SettingsView(self.factory)
        for page in (
            self.dashboard,
            self.projection,
            self.transactions,
            self.history,
            self.portfolios,
            self.settings,
        ):
            self.stack.addWidget(page)
        main_layout.addWidget(self.stack, 1)
        outer.addWidget(main, 1)

        self.dashboard.refresh_requested.connect(self.refresh_prices)
        self.transactions.saved.connect(self._reload_data)
        self.history.data_changed.connect(self._reload_data)
        self.portfolios.data_changed.connect(self._reload_data)
        self.settings.data_changed.connect(self._reload_data)
        self.statusBar().showMessage("Ready")
        self._create_actions()
        self.show_page(0)

    def _create_actions(self) -> None:
        refresh = QAction("Refresh Prices", self)
        refresh.setShortcut(QKeySequence("Ctrl+R"))
        refresh.triggered.connect(
            lambda: self.refresh_prices(self.dashboard.portfolio.currentData(), False)
        )
        self.addAction(refresh)
        new_transaction = QAction("New Transaction", self)
        new_transaction.setShortcut(QKeySequence("Ctrl+N"))
        new_transaction.triggered.connect(
            lambda: self.show_page(self.PAGE_NAMES.index("Transactions"))
        )
        self.addAction(new_transaction)
        focus_search = QAction("Focus History Filter", self)
        focus_search.setShortcut(QKeySequence("Ctrl+F"))
        focus_search.triggered.connect(self._focus_history)
        self.addAction(focus_search)
        edit = QAction("Edit Selected Transaction", self)
        edit.setShortcut(QKeySequence("Ctrl+E"))
        edit.triggered.connect(self._edit_history)
        self.addAction(edit)

    def _focus_history(self) -> None:
        self.show_page(self.PAGE_NAMES.index("History"))
        self.history.search.setFocus()

    def _edit_history(self) -> None:
        self.show_page(self.PAGE_NAMES.index("History"))
        self.history.edit_selected()

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.title.setText(self.PAGE_NAMES[index])
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        page_name = self.PAGE_NAMES[index]
        if page_name == "Projection" and self.isVisible():
            QTimer.singleShot(0, self.projection.ensure_chart)
        elif page_name == "History":
            self.history.reload()
        elif page_name == "Portfolios":
            self.portfolios.reload()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        if (
            self.PAGE_NAMES[self.stack.currentIndex()] == "Projection"
            and self.projection.chart is None
        ):
            QTimer.singleShot(0, self.projection.ensure_chart)

    def _reload_data(self) -> None:
        self.dashboard.reload_portfolios()
        self.projection.reload_portfolios()
        self.transactions.reload_context()
        self.history.reload()
        self.portfolios.reload()

    def refresh_prices(self, portfolio_id: int | None, retry: bool = False) -> None:
        try:
            token = get_finmind_token()
        except Exception as error:  # noqa: BLE001 - credential backend boundary
            QMessageBox.warning(
                self, "Refresh Prices", f"The FinMind token could not be read: {error}"
            )
            return
        if not token:
            QMessageBox.information(
                self, "Refresh Prices", "Save a FinMind token under Settings first."
            )
            return
        self.statusBar().showMessage("Refreshing daily prices…")
        today = datetime.now().astimezone().date()
        worker = FunctionWorker(
            lambda: refresh_prices(
                self.factory, FinMindProvider(token), today, portfolio_id, retry
            )
        )
        worker.signals.result.connect(self._refresh_complete)
        worker.signals.error.connect(
            lambda error: QMessageBox.warning(self, "Refresh Prices", error)
        )
        worker.signals.finished.connect(
            lambda: self.statusBar().showMessage("Ready", 3000)
        )
        self.pool.start(worker)

    def _refresh_complete(self, result: object) -> None:
        self.dashboard.reload()
        self.projection.reload()
        failures = getattr(result, "failed", ())
        refreshed = len(getattr(result, "refreshed", ()))
        cached = len(getattr(result, "cached", ()))
        message = f"Refreshed {refreshed}; already cached {cached}."
        if failures:
            message += "\n\nFailures:\n" + "\n".join(
                f"{symbol}: {error}" for symbol, error in failures
            )
            QMessageBox.warning(self, "Refresh completed with errors", message)
        else:
            self.statusBar().showMessage(message, 5000)
