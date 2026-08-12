from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from irr_calculator.models import Portfolio, Quote, Security


def test_foreign_keys_uniqueness_and_positive_quotes(db):
    _engine, factory, (_portfolio_id, security_id) = db
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(Portfolio(name="Core"))
    with pytest.raises(IntegrityError), factory.begin() as session:
        session.add(Security(provider="FinMind", symbol="2330", name_zh="duplicate"))
    with pytest.raises(IntegrityError), factory.begin() as session:
        today = __import__("datetime").date.today()
        session.add(Quote(security_id=security_id, market_date=today, refresh_cycle_date=today, close=Decimal("0")))


def test_local_search_supports_code_and_chinese_name(db):
    from irr_calculator.services.securities import search_securities
    _engine, factory, _ids = db
    with factory() as session:
        assert [item.symbol for item in search_securities(session, "233")] == ["2330"]
        assert [item.symbol for item in search_securities(session, "積電")] == ["2330"]
        assert search_securities(session, "nothing") == []
