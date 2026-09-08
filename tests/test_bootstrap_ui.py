from threading import Event, get_ident

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from sqlalchemy import select

from financial_hub import app as app_module
from financial_hub.exceptions import ProviderError
from financial_hub.models import Security
from financial_hub.providers.base import SecurityInfo
from financial_hub.ui.main_window import MainWindow


def test_startup_is_responsive_and_reloads_after_download(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "default.sqlite3"
    monkeypatch.setattr(app_module, "default_database_path", lambda: path)
    monkeypatch.setattr(app_module, "get_finmind_token", lambda: "")
    started, release = Event(), Event()
    threads = []

    class Provider:
        def security_master(self):
            threads.append(get_ident())
            started.set()
            assert release.wait(5)
            return (SecurityInfo("00692", "ETF", "twse", "etf"),)

    monkeypatch.setattr(app_module, "FinMindProvider", lambda token: Provider())
    app, window = app_module.build_application([])
    qtbot.addWidget(window)
    reloads = []
    monkeypatch.setattr(
        window.transactions, "reload_context", lambda: reloads.append(True)
    )
    assert not started.is_set()
    try:
        window.show()
        qtbot.waitUntil(started.is_set)
        assert window.isVisible()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        qtbot.waitUntil(lambda: bool(ticks))
        transactions_index = window.PAGE_NAMES.index("Transactions")
        window.show_page(transactions_index)
        assert window.stack.currentIndex() == transactions_index
        assert "Loading security list" in window.statusBar().currentMessage()
        assert threads == [threads[0]] and threads[0] != get_ident()
        assert not window.settings.sync_button.isEnabled()
        window.settings.sync_master()
        window.settings.retry_sync()
        assert len(threads) == 1
        release.set()
        qtbot.waitUntil(lambda: not window.settings._sync_in_progress)
        assert reloads == [True]
        with window.factory() as session:
            assert session.scalar(select(Security.symbol)) == "00692"
        window.hide()
        window.show()
        QApplication.processEvents()
        assert len(threads) == 1
    finally:
        release.set()
        window.shutdown()
        app.aboutToQuit.disconnect(window.shutdown)


def test_failed_bootstrap_can_retry_without_overlapping_manual_sync(qtbot, db):
    _, factory, _ = db
    attempts = []

    def download():
        attempts.append(True)
        if len(attempts) == 1:
            raise ProviderError("Offline")
        return 1

    window = MainWindow(factory, bootstrap=download)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.sync_retry_button.isVisible())
    assert "Offline" in window.statusBar().currentMessage()
    assert window.settings.sync_button.isEnabled()
    window.sync_retry_button.click()
    qtbot.waitUntil(
        lambda: len(attempts) == 2 and not window.settings._sync_in_progress
    )
    assert not window.sync_retry_button.isVisible()
    assert "1 records" in window.statusBar().currentMessage()


def test_close_waits_responsively_for_download(qtbot, db):
    _, factory, _ = db
    started, release = Event(), Event()

    def download():
        started.set()
        assert release.wait(5)
        return 1

    window = MainWindow(factory, bootstrap=download)
    qtbot.addWidget(window)
    try:
        window.show()
        qtbot.waitUntil(started.is_set)
        window.close()
        assert window.isVisible()
        assert "before closing" in window.statusBar().currentMessage()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        qtbot.waitUntil(lambda: bool(ticks))
        release.set()
        qtbot.waitUntil(lambda: not window.isVisible())
        assert window._worker_pool.activeThreadCount() == 0
    finally:
        release.set()
        window.shutdown()


@pytest.mark.parametrize("populated", [False, True])
def test_bootstrap_eligibility(qtbot, db, tmp_path, monkeypatch, populated):
    engine, _, _ = db
    path = tmp_path / "other.sqlite3"
    default = engine.url.database if populated else tmp_path / "default.sqlite3"
    monkeypatch.setattr(
        app_module, "default_database_path", lambda: app_module.Path(default)
    )
    calls = []
    monkeypatch.setattr(
        app_module, "bootstrap_new_database", lambda factory: calls.append(True)
    )
    app, window = app_module.build_application(
        database_path=default if populated else path
    )
    qtbot.addWidget(window)
    try:
        window.show()
        QApplication.processEvents()
        assert window._bootstrap is None
        assert calls == []
    finally:
        window.shutdown()
        app.aboutToQuit.disconnect(window.shutdown)
