from PyQt6.QtCore import Qt

from irr_calculator.ui.main_window import MainWindow


def test_main_window_navigation_and_deferred_chart(qtbot, db):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    assert window.stack.currentIndex() == 0
    assert window.dashboard.chart is None
    window.show()
    qtbot.waitUntil(lambda: window.dashboard.chart is not None, timeout=5000)
    qtbot.mouseClick(window.nav_buttons[2], Qt.MouseButton.LeftButton)
    assert window.stack.currentIndex() == 2
    assert window.title.text() == "History"


def test_transaction_table_model():
    from irr_calculator.ui.models import TransactionTableModel
    model = TransactionTableModel([(42, "2025-01-01", "Core", "2330", "BUY", 10, -100, 0, "Active")])
    assert model.rowCount() == 1
    assert model.columnCount() == 8
    assert model.index(0, 0).data() == "2025-01-01"
    assert model.index(0, 0).data(Qt.ItemDataRole.UserRole) == 42
