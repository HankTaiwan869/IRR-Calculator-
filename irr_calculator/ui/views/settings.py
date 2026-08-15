from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

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

from ... import __version__
from ...database import backup_database
from ...legacy_import import import_legacy_database
from ...preferences import save_finmind_token
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

        application = QGroupBox("Application")
        application_form = QFormLayout(application)
        self.version_value = QLabel(__version__)
        application_form.addRow("Version", self.version_value)
        layout.addWidget(application)

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

        migration = QGroupBox("Legacy import")
        migration_form = QFormLayout(migration)
        self.import_status = QLabel(
            "Import the original log table, then add opening positions from the Transactions workflow."
        )
        self.import_status.setWordWrap(True)
        self.import_status.setObjectName("muted")
        import_button = QPushButton("Choose Legacy Database…")
        migration_form.addRow(self.import_status)
        migration_form.addRow(import_button)
        layout.addWidget(migration)

        backup = QGroupBox("Database & privacy")
        backup_layout = QVBoxLayout(backup)
        backup_layout.addWidget(
            QLabel(
                "Portfolio data stays under %LOCALAPPDATA%\\IRRCalculator. The FinMind token is stored in Windows Credential Manager."
            )
        )
        backup_button = QPushButton("Back Up Database…")
        backup_layout.addWidget(backup_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(backup)
        layout.addStretch()
        save.clicked.connect(self.save_token)
        test.clicked.connect(self.test_token)
        sync.clicked.connect(self.sync_master)
        import_button.clicked.connect(self.import_legacy)
        backup_button.clicked.connect(self.backup_database)

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
        from ...preferences import get_finmind_token

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

    def import_legacy(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select legacy SQLite database",
            "",
            "SQLite databases (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not filename:
            return
        try:
            with self.factory.begin() as session:
                result = import_legacy_database(session, Path(filename))
        except Exception as error:  # noqa: BLE001 - file import boundary
            QMessageBox.warning(self, "Legacy import", str(error))
            return
        if result.already_imported:
            self.import_status.setText(
                f"Already imported ({result.imported_rows} rows). No duplicates were created."
            )
        else:
            self.import_status.setText(
                f"Imported {result.imported_rows} rows. Backup: {result.backup_path}"
            )
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
