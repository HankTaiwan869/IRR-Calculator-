from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QLabel, QLineEdit, QMessageBox

from irr_calculator.models import Security, Transaction, TransactionKind
from irr_calculator.ui.dialogs.transaction import TransactionDialog
from irr_calculator.ui.views.transactions import TransactionsView


def test_create_form_clears_values_that_do_not_apply_after_kind_change(qtbot, db):
    _engine, factory, _ids = db
    view = TransactionsView(factory)
    qtbot.addWidget(view)

    view.shares.setValue(10)
    view.trade_amount.setValue(1_000)
    view.cash_flow.setValue(-1_000)
    view.income.setValue(30)

    view.kind.setCurrentIndex(view.kind.findData(TransactionKind.DIVIDEND))

    assert not view.shares.isEnabled()
    assert view.shares.value() == 0
    assert not view.trade_amount.isEnabled()
    assert view.trade_amount.value() == 0
    assert view.income.value() == 30
    assert view.cash_flow.value() == -1_000

    view.shares.setValue(12)
    view.trade_amount.setValue(900)
    view.cash_flow.setValue(-900)
    view.income.setValue(40)
    view.kind.setCurrentIndex(view.kind.findData(TransactionKind.OPENING_POSITION))

    assert view.shares.value() == 12
    assert view.trade_amount.value() == 900
    assert not view.cash_flow.isEnabled()
    assert view.cash_flow.value() == 0
    assert not view.income.isEnabled()
    assert view.income.value() == 0


def test_create_form_trade_date_cannot_exceed_today(qtbot, db):
    _engine, factory, _ids = db
    view = TransactionsView(factory)
    qtbot.addWidget(view)

    assert view.trade_date.maximumDate() == QDate.currentDate()
    view.trade_date.setDate(QDate.currentDate().addDays(1))
    assert view.trade_date.date() == QDate.currentDate()


def test_security_is_plain_text_and_resolves_exactly_on_save(qtbot, db, monkeypatch):
    _engine, factory, _ids = db
    with factory.begin() as session:
        security = Security(
            provider="FinMind", symbol="00692", name_zh="富邦公司治理",
            exchange="twse", security_type="etf",
        )
        session.add(security)
        session.flush()
        security_id = security.id

    view = TransactionsView(factory)
    qtbot.addWidget(view)
    assert isinstance(view.security, QLineEdit)
    assert not hasattr(view, "search_timer")
    qtbot.keyClicks(view.security, "00692")
    assert view.security.text() == "00692"

    captured = []
    warnings = []
    monkeypatch.setattr("irr_calculator.ui.views.transactions.create_transaction", lambda _session, data: captured.append(data))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args[-1]))
    view.shares.setValue(1)
    view.trade_amount.setValue(100)
    view.cash_flow.setValue(-100)
    view.save()
    assert captured[0].security_id == security_id

    captured.clear()
    view.security.setText("0069")
    view.save()
    assert captured == []
    assert "exact symbol" in warnings[-1]


def test_transaction_amount_widgets_display_whole_numbers(qtbot, db):
    _engine, factory, _ids = db
    view = TransactionsView(factory)
    qtbot.addWidget(view)

    for widget in (view.shares, view.trade_amount, view.cash_flow, view.income):
        assert widget.decimals() == 0


def test_edit_transaction_widgets_display_whole_numbers(qtbot, db):
    _engine, factory, (portfolio_id, security_id) = db
    transaction = Transaction(
        portfolio_id=portfolio_id,
        security_id=security_id,
        kind=TransactionKind.BUY.value,
        trade_date=QDate.currentDate().toPyDate(),
        shares_delta=2,
        external_cash_flow=-200,
        trade_amount=200,
        income_amount=0,
    )
    dialog = TransactionDialog(factory, transaction)
    qtbot.addWidget(dialog)

    for widget in (dialog.shares, dialog.cash, dialog.trade, dialog.income):
        assert widget.decimals() == 0


def test_create_form_submits_integer_values(qtbot, db, monkeypatch):
    _engine, factory, _ids = db
    view = TransactionsView(factory)
    qtbot.addWidget(view)
    captured = []
    monkeypatch.setattr("irr_calculator.ui.views.transactions.create_transaction", lambda _session, data: captured.append(data))
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)

    view.kind.setCurrentIndex(view.kind.findData(TransactionKind.BUY))
    view.security.setText("2330")
    view.shares.setValue(3)
    view.cash_flow.setValue(-100)
    view.trade_amount.setValue(100)
    view.save()

    data = captured[0]
    for value in (data.shares_delta, data.external_cash_flow, data.trade_amount, data.income_amount):
        assert type(value) is int


def test_removed_transaction_inputs_are_absent_from_create_and_edit_forms(qtbot, db):
    _engine, factory, (portfolio_id, security_id) = db
    transaction = Transaction(
        portfolio_id=portfolio_id,
        security_id=security_id,
        kind=TransactionKind.BUY.value,
        trade_date=QDate.currentDate().toPyDate(),
        shares_delta=2,
        external_cash_flow=-200,
        trade_amount=200,
        income_amount=0,
    )
    view = TransactionsView(factory)
    dialog = TransactionDialog(factory, transaction)
    qtbot.addWidget(view)
    qtbot.addWidget(dialog)

    removed = {"Exchange", "Security type", "Unit price (optional)", "Unit price", "Fees", "Notes"}
    assert removed.isdisjoint(label.text() for label in view.findChildren(QLabel))
    assert removed.isdisjoint(label.text() for label in dialog.findChildren(QLabel))


def test_edit_form_trade_date_cannot_exceed_today(qtbot, db):
    _engine, factory, (portfolio_id, security_id) = db
    transaction = Transaction(
        portfolio_id=portfolio_id,
        security_id=security_id,
        kind=TransactionKind.OPENING_POSITION.value,
        trade_date=QDate.currentDate().toPyDate(),
        shares_delta=1,
        external_cash_flow=0,
        trade_amount=0,
        income_amount=0,
    )
    dialog = TransactionDialog(factory, transaction)
    qtbot.addWidget(dialog)

    assert dialog.trade_date.maximumDate() == QDate.currentDate()
    dialog.trade_date.setDate(QDate.currentDate().addDays(1))
    assert dialog.trade_date.date() == QDate.currentDate()
