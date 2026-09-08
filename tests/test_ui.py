from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from financial_hub.app import application_icon_path
from financial_hub.ui.main_window import MainWindow


def test_main_window_navigation_includes_personal_finance_and_keeps_indexes(qtbot, db):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    window.show()
    expected_pages = (
        "Dashboard",
        "Transactions",
        "Portfolios",
        "History",
        "Personal Finance",
        "Settings",
    )
    assert window.PAGE_NAMES == expected_pages
    assert window.stack.count() == len(expected_pages)
    assert [button.text() for button in window.nav_buttons] == list(expected_pages)

    for index, page_name in enumerate(expected_pages):
        qtbot.mouseClick(window.nav_buttons[index], Qt.MouseButton.LeftButton)
        assert window.stack.currentIndex() == index
        assert window.title.text() == page_name


def test_transaction_table_model():
    from financial_hub.ui.models import TransactionTableModel

    model = TransactionTableModel(
        [(42, "2025-01-01", "Core", "2330", "BUY", 10, -100)]
    )
    assert model.rowCount() == 1
    assert model.columnCount() == 6
    assert model.index(0, 0).data() == "2025-01-01"
    assert model.index(0, 0).data(Qt.ItemDataRole.UserRole) == 42


def test_application_icon_is_available():
    icon_path = application_icon_path()
    assert icon_path.name == "investment.ico"
    assert icon_path.parent.name == "assets"
    assert icon_path.is_file()
    assert not QIcon(str(icon_path)).isNull()
