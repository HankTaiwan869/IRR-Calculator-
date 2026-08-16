from itertools import pairwise

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractSpinBox, QFormLayout, QGroupBox

from financial_hub.ui.main_window import MainWindow


def test_projection_is_separate_from_dashboard_and_years_accept_zero(qtbot, db):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    window.show()

    assert window.PAGE_NAMES[1] == "Projection"
    assert not hasattr(window.dashboard, "years")
    assert set(window.dashboard.cards) == {
        "Total assets",
        "Total profit",
        "Annual IRR",
        "Monthly IRR",
        "Dividend income",
    }
    years = window.projection.years
    assert years.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    assert all(
        control.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
        for control in window.projection.rates
    )
    assert years.minimum() == 0
    assert years.maximum() == 100
    assert not years.keyboardTracking()

    window.stack.setCurrentWidget(window.projection)
    years.setFocus()
    years.lineEdit().selectAll()
    qtbot.keyClicks(years, "0")
    qtbot.keyPress(years, Qt.Key.Key_Return)
    assert years.value() == 0

    years.lineEdit().selectAll()
    qtbot.keyClicks(years, "30")
    qtbot.keyPress(years, Qt.Key.Key_Return)
    assert years.value() == 30

    years.stepUp()
    assert years.value() == 31


def test_accounting_details_form_has_room_between_rows(qtbot, db):
    _engine, factory, _ids = db
    window = MainWindow(factory)
    qtbot.addWidget(window)
    window.show_page(window.PAGE_NAMES.index("Transactions"))
    window.resize(900, 620)
    window.show()
    qtbot.waitExposed(window)

    accounting = next(
        group
        for group in window.transactions.findChildren(QGroupBox)
        if group.title() == "Accounting details"
    )
    form = accounting.layout()
    assert isinstance(form, QFormLayout)
    assert form.verticalSpacing() == 14
    assert form.horizontalSpacing() == 24
    assert form.contentsMargins().top() == 30

    fields = (
        window.transactions.shares,
        window.transactions.amount,
    )
    assert all(field.height() >= 42 for field in fields)
    gaps = [
        lower.geometry().top() - upper.geometry().bottom() - 1
        for upper, lower in pairwise(fields)
    ]
    assert min(gaps) >= 14
    assert window.transactions.verticalScrollBar().maximum() == 0
