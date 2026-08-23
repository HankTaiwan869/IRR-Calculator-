from __future__ import annotations

from datetime import datetime, timedelta

from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...credentials import save_finmind_token
from ...data_import import import_transactions
from ...database import backup_database
from ...providers import FinMindProvider
from ...services.quotes import sync_security_master
from ..workers import FunctionWorker


class SettingsView(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, session_factory, parent=None) -> None:
        super().__init__(parent)
        self.factory = session_factory
        self.pool = QThreadPool.globalInstance()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 12, 20)
        layout.setSpacing(14)

        provider = QGroupBox("FinMind provider")
        provider_form = QFormLayout(provider)
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("Token is loaded only when you save or refresh")
        save = QPushButton("Save Token")
        test = QPushButton("Test Token")
        sync = QPushButton("Sync Security Master")
        sync.setObjectName("primary")
        self.sync_status = QLabel(
            "Security data is local and never synced during startup."
        )
        self.sync_status.setObjectName("muted")
        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addWidget(test)
        buttons.addWidget(sync)
        buttons.addStretch()
        provider_form.addRow("FinMind token", self.token)
        provider_form.addRow(buttons)
        provider_form.addRow(self.sync_status)
        layout.addWidget(provider)

        backup = QGroupBox("Database")
        backup_layout = QVBoxLayout(backup)
        import_button = QPushButton("Import from Excel/SQLite")
        backup_button = QPushButton("Back Up Database…")
        backup_layout.addWidget(import_button, alignment=Qt.AlignmentFlag.AlignLeft)
        backup_layout.addWidget(backup_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(backup)
        layout.addStretch()
        save.clicked.connect(self.save_token)
        test.clicked.connect(self.test_token)
        sync.clicked.connect(self.sync_master)
        backup_button.clicked.connect(self.backup_database)
        import_button.clicked.connect(self.import_file)

    def save_token(self) -> None:
        try:
            save_finmind_token(self.token.text())
            self.token.clear()
            QMessageBox.information(
                self, "FinMind", "Token saved in Windows Credential Manager."
            )
        except Exception as error:  # noqa: BLE001 - credential backend boundary
            QMessageBox.warning(
                self, "FinMind", f"The token could not be saved: {error}"
            )

    def _token_value(self) -> str | None:
        token = self.token.text().strip()
        if token:
            return token
        from ...credentials import get_finmind_token

        try:
            return get_finmind_token()
        except Exception as error:  # noqa: BLE001 - credential backend boundary
            QMessageBox.warning(
                self, "FinMind", f"The saved token could not be read: {error}"
            )
            return None

    def test_token(self) -> None:
        token = self._token_value()
        if not token:
            QMessageBox.information(
                self, "FinMind", "Enter or save a FinMind token first."
            )
            return
        self.sync_status.setText("Testing FinMind access…")
        start_date = datetime.now().astimezone().date() - timedelta(days=10)
        worker = FunctionWorker(
            lambda: FinMindProvider(token).latest_quote("2330", start_date)
        )
        worker.signals.result.connect(
            lambda quote: self.sync_status.setText(
                f"Connection succeeded. 2330 close: {quote.close} ({quote.market_date})"
            )
        )
        worker.signals.error.connect(
            lambda error: self.sync_status.setText(f"Connection test failed: {error}")
        )
        self.pool.start(worker)

    def sync_master(self) -> None:
        token = self._token_value()
        if not token:
            QMessageBox.information(
                self, "FinMind", "Enter or save a FinMind token first."
            )
            return
        self.sync_status.setText("Syncing security master…")

        def work() -> int:
            provider = FinMindProvider(token)
            with self.factory.begin() as session:
                return sync_security_master(session, provider)

        worker = FunctionWorker(work)
        worker.signals.result.connect(self._sync_complete)
        worker.signals.error.connect(
            lambda error: self.sync_status.setText(f"Sync failed: {error}")
        )
        self.pool.start(worker)

    def _sync_complete(self, count: object) -> None:
        self.sync_status.setText(f"Security master updated: {count} records.")
        self.data_changed.emit()

    def backup_database(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Back up portfolio database",
            "portfolio-backup.sqlite3",
            "SQLite database (*.sqlite3)",
        )
        if not filename:
            return
        try:
            engine = self.factory.kw["bind"]
            target = backup_database(engine, filename)
            QMessageBox.information(
                self, "Database backup", f"Backup created at:\n{target}"
            )
        except Exception as error:  # noqa: BLE001 - filesystem boundary
            QMessageBox.warning(self, "Database backup", str(error))

    def import_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import cash flows",
            "",
            "Supported files (*.xlsx *.db *.sqlite *.sqlite3);;"
            "Excel workbook (*.xlsx);;SQLite database (*.db *.sqlite *.sqlite3)",
        )
        if not filename:
            return
        try:
            with self.factory.begin() as session:
                result = import_transactions(session, filename)
            QMessageBox.information(
                self,
                "Import complete",
                f"Imported {result.imported_rows} cash-flow rows.",
            )
            self.data_changed.emit()
        except Exception as error:  # noqa: BLE001 - import boundary
            QMessageBox.warning(self, "Import failed", str(error))
