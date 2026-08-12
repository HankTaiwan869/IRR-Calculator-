from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pyxirr import xirr
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from ..models import Quote, Security, Transaction
from .ledger import replay_ledger

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class Position:
    security_id: int
    symbol: str
    shares: Decimal
    cost_basis: Decimal
    market_value: Decimal | None
    realized_profit: Decimal
    dividend_income: Decimal
    cost_basis_complete: bool


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    total_assets: Decimal
    cost_basis: Decimal
    realized_profit: Decimal
    unrealized_profit: Decimal | None
    dividend_income: Decimal
    total_profit: Decimal | None
    annual_irr: float | None
    monthly_irr: float | None
    positions: tuple[Position, ...]


def _transactions_query(portfolio_id: int | None) -> Select[tuple[Transaction]]:
    query = select(Transaction).where(Transaction.deleted_at.is_(None))
    return query if portfolio_id is None else query.where(Transaction.portfolio_id == portfolio_id)


def calculate_xirr(rows: list[Transaction], terminal_value: Decimal, valuation_date: date) -> float | None:
    dated = [(row.trade_date, float(row.external_cash_flow)) for row in rows if row.external_cash_flow != ZERO]
    if terminal_value != ZERO:
        dated.append((valuation_date, float(terminal_value)))
    values = [amount for _, amount in dated]
    if not dated or not any(value < 0 for value in values) or not any(value > 0 for value in values):
        return None
    try:
        result = xirr([day for day, _ in dated], values)
        return None if result is None else float(result)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        return None


def portfolio_summary(session: Session, valuation_date: date, portfolio_id: int | None = None) -> PortfolioSummary:
    rows = list(session.scalars(_transactions_query(portfolio_id).order_by(Transaction.trade_date, Transaction.id)))
    by_security: dict[int, list[Transaction]] = {}
    for row in rows:
        if row.security_id is not None:
            by_security.setdefault(row.security_id, []).append(row)

    positions: list[Position] = []
    for security_id, ledger_rows in by_security.items():
        ledger = replay_ledger(ledger_rows)
        security = session.get(Security, security_id)
        quote = session.scalar(
            select(Quote).where(Quote.security_id == security_id, Quote.market_date <= valuation_date)
            .order_by(Quote.market_date.desc()).limit(1)
        )
        market_value = None if quote is None else ledger.shares * quote.close
        positions.append(Position(
            security_id=security_id,
            symbol=security.symbol if security else str(security_id),
            shares=ledger.shares,
            cost_basis=ledger.cost_basis,
            market_value=market_value,
            realized_profit=ledger.realized_profit,
            dividend_income=ledger.dividend_income,
            cost_basis_complete=ledger.cost_basis_complete,
        ))

    total_assets = sum((item.market_value or ZERO for item in positions), ZERO)
    cost_basis = sum((item.cost_basis for item in positions), ZERO)
    realized = sum((item.realized_profit for item in positions), ZERO)
    dividends = sum((item.dividend_income for item in positions), ZERO)
    missing_open_value = any(item.shares != ZERO and item.market_value is None for item in positions)
    unrealized = None if missing_open_value else total_assets - cost_basis
    total_profit = None if unrealized is None else unrealized + realized + dividends
    annual = None if missing_open_value else calculate_xirr(rows, total_assets, valuation_date)
    monthly = None if annual is None or annual <= -1 else (1 + annual) ** (1 / 12) - 1
    return PortfolioSummary(total_assets, cost_basis, realized, unrealized, dividends, total_profit, annual, monthly, tuple(positions))


def projection(principal: Decimal, years: int = 30, rates: tuple[Decimal, ...] = (Decimal("0.065"), Decimal("0.09"), Decimal("0.115"))) -> tuple[tuple[Decimal, ...], ...]:
    return tuple(tuple(principal * ((Decimal("1") + rate) ** year) for year in range(years + 1)) for rate in rates)
