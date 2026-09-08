from __future__ import annotations

from financial_hub.services.personal_finance import (
    list_annual_snapshots,
    list_monthly_records,
)
from financial_hub.ui.views.personal_finance import PersonalFinanceView


def test_personal_finance_view_has_two_tabs_and_preserves_blank_vs_zero(qtbot, db):
    _engine, factory, _ids = db
    view = PersonalFinanceView(factory)
    qtbot.addWidget(view)

    assert view.tabs.count() == 2
    assert view.monthly_table.rowCount() == 12
    assert view.yearly_table.columnCount() == 9

    view.monthly_table.item(0, 1).setText("0")
    view.monthly_table.item(0, 2).setText("1,250")
    assert view.monthly_table.item(0, 3).text() == "-1,250"
    assert "Income coverage: 1/12" in view.monthly_coverage.text()
    assert view.monthly_table.item(1, 1).text() == ""
    assert view.monthly_table.item(1, 2).text() == ""


def test_personal_finance_view_saves_monthly_and_annual_entries(qtbot, db):
    _engine, factory, _ids = db
    view = PersonalFinanceView(factory)
    qtbot.addWidget(view)
    view.year_selector.setValue(2024)
    view.monthly_table.item(0, 1).setText("100")
    view.monthly_table.item(0, 2).setText("40")
    view.save_monthly()

    with factory() as session:
        monthly = list_monthly_records(session, 2024)
    assert len(monthly) == 12
    assert monthly[0].income == 100
    assert monthly[0].expenditure == 40
    assert monthly[1].income is None

    row = view._yearly_row_index(2024)
    assert row >= 0
    view.yearly_table.item(row, 1).setText("500")
    view.yearly_table.item(row, 2).setText("800")
    view.yearly_table.item(row, 3).setText("100")
    assert view.yearly_table.item(row, 4).text() == "1,200"
    view.save_yearly()

    with factory() as session:
        annual = list_annual_snapshots(session)
    assert annual[0].total_asset_excluding_investment == 500
    assert annual[0].total_portfolio_value == 800
    assert annual[0].total_debt == 100
    assert view.yearly_table.item(row, 5).text() == "100"
    assert view.yearly_table.item(row, 6).text() == "40"
    assert view.yearly_table.item(row, 7).text() == "1/12 months"
    assert view.yearly_table.item(row, 8).text() == "1/12 months"


def test_adding_year_keeps_existing_yearly_edits(qtbot, db):
    _engine, factory, _ids = db
    view = PersonalFinanceView(factory)
    qtbot.addWidget(view)
    existing = view._yearly_row_index(view.new_year_selector.value())
    view.yearly_table.item(existing, 1).setText("123")

    view.new_year_selector.setValue(view.new_year_selector.value() - 1)
    view.add_year()

    existing = view._yearly_row_index(view.new_year_selector.value() + 1)
    assert view.yearly_table.item(existing, 1).text() == "123"
