from __future__ import annotations

import pytest

from irr_calculator.database import (
    create_database_engine,
    initialize_database,
    session_factory,
)
from irr_calculator.models import Portfolio, Security


@pytest.fixture
def db(tmp_path):
    engine = create_database_engine(tmp_path / "test.sqlite3")
    initialize_database(engine)
    factory = session_factory(engine)
    with factory.begin() as session:
        portfolio = Portfolio(name="Core")
        security = Security(
            provider="FinMind",
            symbol="2330",
            name_zh="台積電",
            exchange="twse",
            security_type="stock",
        )
        session.add_all((portfolio, security))
        session.flush()
        ids = (portfolio.id, security.id)
    yield engine, factory, ids
    engine.dispose()
