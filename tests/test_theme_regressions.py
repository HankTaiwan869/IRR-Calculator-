from decimal import Decimal

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from financial_hub.ui.models import TransactionTableModel
from financial_hub.ui.theme import COLORS, stylesheet
from financial_hub.ui.views.dashboard import money


def test_sidebar_navigation_rule_overrides_generic_button_rule():
    css = stylesheet()
    generic = css.index("QPushButton {")
    nav = css.index("QWidget#sidebar QPushButton#navButton {")

    assert nav > generic
    assert f"background-color: {COLORS['sidebar']}" in css[nav:]
    assert f"color: {COLORS['sidebar_text']}" in css[nav:]


def test_inactive_sidebar_button_actually_renders_dark(qtbot):
    sidebar = QWidget()
    sidebar.setObjectName("sidebar")
    sidebar.setFixedSize(230, 100)
    layout = QVBoxLayout(sidebar)
    button = QPushButton("Dashboard")
    button.setObjectName("navButton")
    button.setCheckable(True)
    layout.addWidget(button)
    sidebar.setStyleSheet(stylesheet())
    qtbot.addWidget(sidebar)
    sidebar.show()
    qtbot.wait(10)

    image = button.grab().toImage()
    background = image.pixelColor(button.width() - 20, button.height() // 2).name()
    assert background == COLORS["sidebar"]


def test_money_and_transaction_history_render_whole_numbers():
    assert money(1234) == "NT$ 1,234"

    model = TransactionTableModel(
        [(1, "2026-01-01", "Core", "2330", "BUY", 10, -1234)]
    )
    assert model.index(0, 4).data(Qt.ItemDataRole.DisplayRole) == "10"
    assert model.index(0, 5).data(Qt.ItemDataRole.DisplayRole) == "-1,234"


def test_money_rounds_decimal_twd_values_half_up():
    assert money(Decimal("1234.50")) == "NT$ 1,235"
    assert money(Decimal("-1234.50")) == "NT$ -1,235"
    assert money(None) == "Not calculable"


def test_percentage_format_retains_decimal_places():
    assert f"{Decimal('0.1234'):.2%}" == "12.34%"
