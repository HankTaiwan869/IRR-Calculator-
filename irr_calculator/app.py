from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from . import __version__
from .database import create_database_engine, ensure_default_portfolio, initialize_database, session_factory
from .ui.main_window import MainWindow
from .ui.theme import stylesheet

APP_USER_MODEL_ID = f"IRRCalculator.Desktop.{__version__}"


def application_icon_path() -> Path:
    return Path(__file__).resolve().parent.parent / "investment.ico"


def build_application(argv: list[str] | None = None, database_path=None) -> tuple[QApplication, MainWindow]:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("IRR Calculator")
    app.setOrganizationName("IRRCalculator")
    icon = QIcon(str(application_icon_path()))
    app.setWindowIcon(icon)
    app.setStyleSheet(stylesheet())
    engine = create_database_engine(database_path)
    initialize_database(engine)
    factory = session_factory(engine)
    with factory.begin() as session:
        ensure_default_portfolio(session)
    window = MainWindow(factory)
    window.setWindowIcon(icon)
    window._database_engine = engine  # retain engine for application lifetime
    app.aboutToQuit.connect(engine.dispose)
    return app, window


def main() -> int:
    app, window = build_application()
    window.show()
    return app.exec()
