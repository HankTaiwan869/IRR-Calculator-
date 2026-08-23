from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QAbstractSpinBox, QLabel, QLineEdit, QMessageBox

from financial_hub.models import Security, Transaction, TransactionKind
from financial_hub.ui.dialogs.transaction import TransactionDialog
from financial_hub.ui.views.transactions import TransactionsView


def test_create_form_uses_unsigned_values_and_activity_signs(qtbot, db, monkeypatch):
    _engine, factory, _ids = db
    view = TransactionsView(factory)
    qtbot.addWidget(view)

    captured = []
    monkeypatch.setattr(
        "financial_hub.ui.views.transactions.create_transaction",
        lambda _session, data: captured.append(data),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    view.security.setText("2330")
    expected = {
        TransactionKind.BUY: (10, -1_000),
        TransactionKind.SELL: (-10, 1_000),
        TransactionKind.DIVIDEND: (0, 1_000),
        TransactionKind.REINVESTED_DIVIDEND: (10, 0),
        TransactionKind.OPENING_POSITION: (10, -1_000),
        TransactionKind.POSITION_RECONCILIATION: (10, 0),
    }
    for kind, signed in expected.items():
        view.kind.setCurrentIndex(view.kind.findData(kind))
        view.shares.setValue(10)
        view.amount.setValue(1_000)
        view.save()
        data = captured[-1]
        assert (data.shares_delta, data.amount) == signed

    view.shares.setValue(10)
    view.amount.setValue(1_000)
    view.kind.setCurrentIndex(view.kind.findData(TransactionKind.DIVIDEND))

    assert not view.shares.isEnabled()
    assert view.shares.value() == 0
    assert view.amount.isEnabled()
    assert view.amount.value() == 1_000

    view.shares.setValue(12)
    view.amount.setValue(900)
    view.kind.setCurrentIndex(view.kind.findData(TransactionKind.REINVESTED_DIVIDEND))
    assert view.shares.value() == 12
    assert not view.amount.isEnabled()
    assert view.amount.value() == 0

    view.kind.setCurrentIndex(view.kind.findData(TransactionKind.POSITION_RECONCILIATION))
    assert view.shares.value() == 12
    assert not view.amount.isEnabled()
    assert view.amount.value() == 0

    view.kind.setCurrentIndex(view.kind.findData(TransactionKind.OPENING_POSITION))
    assert view.shares.value() == 12
    assert view.amount.isEnabled()
    assert view.amount.value() == 0


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
            symbol="00692",
            name_zh="富邦公司治理",
            exchange="twse",
            security_type="etf",
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
    monkeypatch.setattr(
        "financial_hub.ui.views.transactions.create_transaction",
        lambda _session, data: captured.append(data),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *_args: warnings.append(_args[-1])
    )
    view.shares.setValue(1)
    view.amount.setValue(100)
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
    for widget in (view.shares, view.amount):
        assert widget.decimals() == 0


def test_edit_transaction_widgets_display_whole_numbers(qtbot, db):
    _engine, factory, (portfolio_id, security_id) = db
    transaction = Transaction(
        portfolio_id=portfolio_id,
        security_id=security_id,
        kind=TransactionKind.BUY.value,
        trade_date=QDate.currentDate().toPyDate(),
        shares_delta=2,
        amount=-200,
    )
    dialog = TransactionDialog(factory, transaction)
    qtbot.addWidget(dialog)
    for widget in (dialog.shares, dialog.amount):
        assert widget.decimals() == 0


def test_transaction_amount_widgets_hide_spinbox_arrows(qtbot, db):
    _engine, factory, (portfolio_id, security_id) = db
    transaction = Transaction(
        portfolio_id=portfolio_id,
        security_id=security_id,
        kind=TransactionKind.BUY.value,
        trade_date=QDate.currentDate().toPyDate(),
        shares_delta=2,
        amount=-200,
    )
    view = TransactionsView(factory)
    dialog = TransactionDialog(factory, transaction)
    qtbot.addWidget(view)
    qtbot.addWidget(dialog)
    for widget in (view.shares, view.amount, dialog.shares, dialog.amount):
        assert widget.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons


def test_edit_form_uses_unsigned_values_and_activity_signs(qtbot, db, monkeypatch):
    _engine, factory, (portfolio_id, security_id) = db
    expected = {
        TransactionKind.BUY: (10, -1_000),
        TransactionKind.SELL: (-10, 1_000),
        TransactionKind.DIVIDEND: (0, 1_000),
        TransactionKind.REINVESTED_DIVIDEND: (10, 0),
        TransactionKind.OPENING_POSITION: (10, -1_000),
        TransactionKind.POSITION_RECONCILIATION: (10, 0),
    }
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    for kind, signed in expected.items():
        transaction = Transaction(
            portfolio_id=portfolio_id,
            security_id=security_id,
            kind=kind.value,
            trade_date=QDate.currentDate().toPyDate(),
            shares_delta=signed[0],
            amount=signed[1],
        )
        dialog = TransactionDialog(factory, transaction)
        qtbot.addWidget(dialog)
        assert dialog.shares.value() == abs(signed[0])
        assert dialog.amount.value() == abs(signed[1])
        dialog.accept()
        data = dialog.result_data
        assert data is not None
        assert (data.shares_delta, data.amount) == signed


def test_legacy_cash_flow_edit_preserves_its_signed_direction(qtbot, db):
    _engine, factory, (portfolio_id, _security_id) = db
    transaction = Transaction(
        portfolio_id=portfolio_id,
        security_id=None,
        kind=TransactionKind.LEGACY_CASH_FLOW.value,
        trade_date=QDate.currentDate().toPyDate(),
        shares_delta=0,
        amount=-200,
    )
    dialog = TransactionDialog(factory, transaction)
    qtbot.addWidget(dialog)

    assert dialog.shares.value() == 0
    assert not dialog.shares.isEnabled()
    assert dialog.amount.minimum() < 0
    assert dialog.amount.value() == -200

    dialog.accept()

    assert dialog.result_data is not None
    assert dialog.result_data.shares_delta == 0
    assert dialog.result_data.amount == -200


def test_removed_transaction_inputs_are_absent_from_create_and_edit_forms(qtbot, db):
    _engine, factory, (portfolio_id, security_id) = db
    transaction = Transaction(
        portfolio_id=portfolio_id,
        security_id=security_id,
        kind=TransactionKind.BUY.value,
        trade_date=QDate.currentDate().toPyDate(),
        shares_delta=2,
        amount=-200,
    )
    view = TransactionsView(factory)
    dialog = TransactionDialog(factory, transaction)
    qtbot.addWidget(view)
    qtbot.addWidget(dialog)
    removed = {
        "Trade amount",
        "External cash flow",
        "Dividend income",
        "Exchange",
        "Security type",
        "Unit price (optional)",
        "Unit price",
        "Fees",
        "Notes",
    }
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
        amount=-100,
    )
    dialog = TransactionDialog(factory, transaction)
    qtbot.addWidget(dialog)
    assert dialog.trade_date.maximumDate() == QDate.currentDate()
    dialog.trade_date.setDate(QDate.currentDate().addDays(1))
    assert dialog.trade_date.date() == QDate.currentDate()
