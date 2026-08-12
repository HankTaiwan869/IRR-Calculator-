from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .database import create_database_engine, ensure_default_portfolio, initialize_database, session_factory
from .ui.main_window import MainWindow
from .ui.theme import stylesheet


def build_application(argv: list[str] | None = None, database_path=None) -> tuple[QApplication, MainWindow]:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("IRR Calculator")
    app.setOrganizationName("IRRCalculator")
    app.setStyleSheet(stylesheet())
    engine = create_database_engine(database_path)
    initialize_database(engine)
    factory = session_factory(engine)
    with factory.begin() as session:
        ensure_default_portfolio(session)
    window = MainWindow(factory)
    window._database_engine = engine  # retain engine for application lifetime
    app.aboutToQuit.connect(engine.dispose)
    return app, window


def main() -> int:
    app, window = build_application()
    window.show()
    return app.exec()
