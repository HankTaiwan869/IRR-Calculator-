from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

from financial_hub.app import application_icon_path
from financial_hub.ui.main_window import MainWindow


def test_main_window_navigation_and_deferred_plotly_chart(qtbot, db):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    assert window.stack.currentIndex() == 0
    assert window.projection.chart is None
    window.show()
    qtbot.mouseClick(window.nav_buttons[1], Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.projection.chart is not None, timeout=5000)
    assert window.stack.currentIndex() == 1
    assert window.title.text() == "Projection"
    assert window.projection.chart.metaObject().className() == "QWebEngineView"
    rendered = []
    script = "typeof Plotly !== 'undefined' && document.querySelector('.plotly-graph-div') !== null"

    def check_rendered():
        def checked(value):
            if value:
                rendered.append(True)
            else:
                QTimer.singleShot(50, check_rendered)

        window.projection.chart.page().runJavaScript(script, checked)

    check_rendered()
    qtbot.waitUntil(lambda: bool(rendered), timeout=5000)
    assert rendered == [True]
    qtbot.mouseClick(window.nav_buttons[3], Qt.MouseButton.LeftButton)
    assert window.stack.currentIndex() == 3
    assert window.title.text() == "Portfolios"


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
