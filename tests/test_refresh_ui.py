import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from financial_hub.services.quotes import RefreshResult
from financial_hub.ui.main_window import MainWindow


class DeferredPool:
    def __init__(self):
        self.workers = []

    def start(self, worker):
        self.workers.append(worker)


@pytest.mark.parametrize("outcome", ["success", "partial_failure", "error"])
def test_refresh_blocks_overlap_and_allows_another_attempt(
    qtbot, db, monkeypatch, outcome
):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    pool = DeferredPool()
    window.pool = pool
    monkeypatch.setattr(
        "financial_hub.ui.main_window.get_finmind_token", lambda: "test-token"
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args: warnings.append(args[2])
    )
    calls = []

    def refresh(*args):
        calls.append(args)
        if outcome == "error":
            raise RuntimeError("Request failed")
        failures = (("0050", "Provider unavailable"),) if outcome == "partial_failure" else ()
        return RefreshResult(("2330",), failures)

    monkeypatch.setattr("financial_hub.ui.main_window.refresh_prices", refresh)

    qtbot.mouseClick(window.dashboard.refresh_button, Qt.MouseButton.LeftButton)
    assert len(pool.workers) == 1
    assert not window.dashboard.refresh_button.isEnabled()

    # Cover button and direct signal entry points while busy.
    qtbot.mouseClick(window.dashboard.refresh_button, Qt.MouseButton.LeftButton)
    window.refresh_prices(None)
    assert len(pool.workers) == 1

    pool.workers[0].run()
    assert len(calls) == 1
    assert window.dashboard.refresh_button.isEnabled()
    assert bool(warnings) == (outcome != "success")
    assert "Refreshing daily prices" not in window.statusBar().currentMessage()
    assert "cached" not in window.statusBar().currentMessage()

    qtbot.mouseClick(window.dashboard.refresh_button, Qt.MouseButton.LeftButton)
    assert len(pool.workers) == 2
    pool.workers[1].run()
    assert len(calls) == 2
    assert window.dashboard.refresh_button.isEnabled()
