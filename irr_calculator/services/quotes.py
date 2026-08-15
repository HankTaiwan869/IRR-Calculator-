from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from ..models import Portfolio, Quote, Security, Transaction
from ..exceptions import ProviderError
from ..providers.base import SecuritiesProvider


@dataclass(frozen=True, slots=True)
class RefreshResult:
    refreshed: tuple[str, ...]
    cached: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]


def _integer_close(value: object) -> int:
    try:
        close = int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ProviderError("The quote provider returned a malformed closing price.") from error
    if close <= 0:
        raise ProviderError("The quote provider returned a non-positive closing price.")
    return close


def sync_security_master(session: Session, provider: SecuritiesProvider) -> int:
    records = provider.security_master()
    for item in records:
        statement = insert(Security).values(
            provider=provider.name, symbol=item.symbol, name_zh=item.name_zh,
            exchange=item.exchange, security_type=item.security_type, active=True,
        ).on_conflict_do_update(
            index_elements=[Security.provider, Security.symbol],
            set_={"name_zh": item.name_zh, "exchange": item.exchange, "security_type": item.security_type, "active": True},
        )
        session.execute(statement)
    return len(records)


def refresh_prices(factory: sessionmaker[Session], provider: SecuritiesProvider, cycle_date: date, portfolio_id: int | None = None, retry: bool = False) -> RefreshResult:
    with factory() as session:
        query = select(Security).join(Transaction, Transaction.security_id == Security.id).where(Transaction.deleted_at.is_(None))
        if portfolio_id is None:
            query = query.join(Portfolio, Transaction.portfolio_id == Portfolio.id).where(Portfolio.archived_at.is_(None))
        else:
            query = query.where(Transaction.portfolio_id == portfolio_id)
        securities = list(session.scalars(query.distinct().order_by(Security.symbol)))
    refreshed: list[str] = []
    cached: list[str] = []
    failed: list[tuple[str, str]] = []
    for security in securities:
        with factory() as session:
            if not retry and session.scalar(select(Quote.id).where(Quote.security_id == security.id, Quote.provider == provider.name, Quote.refresh_cycle_date == cycle_date)):
                cached.append(security.symbol)
                continue
        try:
            quote = provider.latest_quote(security.symbol, cycle_date - timedelta(days=10))
            close = _integer_close(quote.close)
            with factory.begin() as session:
                statement = insert(Quote).values(
                    security_id=security.id, provider=provider.name,
                    market_date=quote.market_date, refresh_cycle_date=cycle_date, close=close,
                ).on_conflict_do_update(
                    index_elements=[Quote.security_id, Quote.provider, Quote.market_date],
                    set_={"close": close, "refresh_cycle_date": cycle_date},
                )
                session.execute(statement)
            refreshed.append(security.symbol)
        except Exception as error:  # provider errors are isolated per symbol
            failed.append((security.symbol, str(error)))
    return RefreshResult(tuple(refreshed), tuple(cached), tuple(failed))
