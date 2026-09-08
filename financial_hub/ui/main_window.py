from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PyQt6.QtCore import QThreadPool, QTimer
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
from ..credentials import get_finmind_token
from ..providers import FinMindProvider
from ..services.quotes import refresh_prices
from .views import (
    DashboardView,
    HistoryView,
    PersonalFinanceView,
    PortfoliosView,
    ProjectionDialog,
    SettingsView,
    TransactionsView,
)
from .workers import FunctionWorker


class MainWindow(QMainWindow):
    PAGE_NAMES = (
        "Dashboard",
        "Transactions",
        "Portfolios",
        "History",
        "Personal Finance",
        "Settings",
    )

    def __init__(
        self,
        session_factory,
        parent=None,
        *,
        bootstrap: Callable[[], int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.factory = session_factory
        self._worker_pool = QThreadPool(self)
        self.pool = self._worker_pool
        self._bootstrap = bootstrap
        self._closing = False
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(50)
        self._close_timer.timeout.connect(self.close)
        self._refresh_in_progress = False
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
        self.projection_dialog = ProjectionDialog(self.factory, self)
        # Keep the view available for the existing refresh/reload coordination,
        # but host it in the Dashboard-launched dialog rather than the stack.
        self.projection = self.projection_dialog.view
        self.transactions = TransactionsView(self.factory)
        self.history = HistoryView(self.factory)
        self.portfolios = PortfoliosView(self.factory)
        self.settings = SettingsView(self.factory)
        self.personal_finance = PersonalFinanceView(self.factory)
        self.settings.pool = self._worker_pool
        for page in (
            self.dashboard,
            self.transactions,
            self.portfolios,
            self.history,
            self.personal_finance,
            self.settings,
        ):
            self.stack.addWidget(page)
        main_layout.addWidget(self.stack, 1)
        outer.addWidget(main, 1)

        self.dashboard.refresh_requested.connect(self.refresh_prices)
        self.dashboard.projection_requested.connect(self.show_projection)
        self.transactions.saved.connect(self._reload_data)
        self.history.data_changed.connect(self._reload_data)
        self.portfolios.data_changed.connect(self._reload_data)
        self.settings.data_changed.connect(self._reload_data)
        self.personal_finance.data_changed.connect(self._reload_data)
        self.settings.sync_message.connect(self._security_sync_message)
        self.sync_retry_button = QPushButton("Retry security download")
        self.sync_retry_button.clicked.connect(self.settings.retry_sync)
        self.statusBar().addPermanentWidget(self.sync_retry_button)
        self.sync_retry_button.hide()
        self.settings.sync_retry_available.connect(self.sync_retry_button.setVisible)
        self._bootstrap_timer = QTimer(self)
        self._bootstrap_timer.setSingleShot(True)
        self._bootstrap_timer.timeout.connect(self._start_bootstrap)
        self.statusBar().showMessage("Ready")
        self.show_page(0)

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.title.setText(self.PAGE_NAMES[index])
        for button_index, button in enumerate(self.nav_buttons):
            button.setChecked(button_index == index)
        page_name = self.PAGE_NAMES[index]
        if page_name == "History":
            self.history.reload()
        elif page_name == "Portfolios":
            self.portfolios.reload()
        elif page_name == "Personal Finance":
            self.personal_finance.reload()

    def show_projection(self, portfolio_id: int | None) -> None:
        self.projection_dialog.open_for_portfolio(portfolio_id)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        if self._bootstrap is not None and not self._closing:
            self._bootstrap_timer.start(0)

    def _start_bootstrap(self) -> None:
        if self._bootstrap is not None and not self._closing:
            work, self._bootstrap = self._bootstrap, None
            self.settings.start_security_sync(work)

    def _security_sync_message(self, message: str) -> None:
        if not self._closing:
            self.statusBar().showMessage(message)

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._closing = True
        self._bootstrap_timer.stop()
        if self._worker_pool.activeThreadCount():
            # Keep widgets alive and process queued signals until workers finish.
            event.ignore()
            self.centralWidget().setEnabled(False)
            self.sync_retry_button.setEnabled(False)
            self.statusBar().showMessage("Finishing background work before closing…")
            self._close_timer.start()
            return
        self._close_timer.stop()
        super().closeEvent(event)

    def shutdown(self) -> None:
        # Explicit QApplication.quit() can bypass closeEvent. Drain workers before
        # disposing the database or allowing their signal receivers to be destroyed.
        self._closing = True
        self._bootstrap_timer.stop()
        self._worker_pool.waitForDone()
        engine = getattr(self, "_database_engine", None)
        if engine is not None:
            engine.dispose()

    def _reload_data(self) -> None:
        self.dashboard.reload_portfolios()
        self.projection.reload_portfolios()
        self.transactions.reload_context()
        self.history.reload()
        self.portfolios.reload()
        self.personal_finance.reload_yearly()

    def refresh_prices(self, portfolio_id: int | None) -> None:
        # This window coordinates a dashboard-initiated refresh because updated
        # prices must also be reflected in the Projection view.
        if self._refresh_in_progress:
            return
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
        self._refresh_in_progress = True
        self.dashboard.refresh_button.setEnabled(False)
        self.statusBar().showMessage("Refreshing daily prices…")
        today = datetime.now().astimezone().date()
        worker = FunctionWorker(
            lambda: refresh_prices(
                self.factory, FinMindProvider(token), today, portfolio_id
            )
        )
        worker.signals.result.connect(self._refresh_complete)
        worker.signals.error.connect(self._refresh_error)
        worker.signals.finished.connect(self._refresh_finished)
        self.pool.start(worker)

    def _refresh_error(self, error: str) -> None:
        self.statusBar().showMessage("Price refresh failed.", 5000)
        QMessageBox.warning(self, "Refresh Prices", error)

    def _refresh_finished(self) -> None:
        self._refresh_in_progress = False
        self.dashboard.refresh_button.setEnabled(True)

    def _refresh_complete(self, result: object) -> None:
        # Refresh both Dashboard & Projection views after the background work succeeds.
        self.dashboard.reload()
        self.projection.reload()
        failures = getattr(result, "failed", ())
        if not failures:
            self.statusBar().showMessage("Success", 5000)
            return

        message = f"Failed to refresh {len(failures)} item(s)."
        message += "\n\nFailures:\n" + "\n".join(
            f"{symbol}: {error}" for symbol, error in failures
        )
        self.statusBar().showMessage(message, 5000)
        QMessageBox.warning(self, "Refresh completed with errors", message)
