from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pyxirr import xirr
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..models import Portfolio, Quote, Security, Transaction
from .ledger import LedgerResult, replay_ledger

ZERO = 0


@dataclass(frozen=True, slots=True)
class Position:
    security_id: int
    symbol: str
    shares: int
    cost_basis: int
    market_value: int | None
    realized_profit: int
    dividend_income: int
    cost_basis_complete: bool


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    total_assets: int | None
    cost_basis: int
    realized_profit: int
    unrealized_profit: int | None
    dividend_income: int
    total_profit: int | None
    annual_irr: float | None
    monthly_irr: float | None
    positions: tuple[Position, ...]


def _transactions_query(portfolio_id: int | None, valuation_date: date) -> Select[tuple[Transaction]]:
    query = select(Transaction).where(
        Transaction.deleted_at.is_(None),
        Transaction.trade_date <= valuation_date,
    )
    if portfolio_id is None:
        return query.join(Portfolio, Transaction.portfolio_id == Portfolio.id).where(Portfolio.archived_at.is_(None))
    return query.where(Transaction.portfolio_id == portfolio_id)


def calculate_xirr(rows: list[Transaction], terminal_value: int, valuation_date: date) -> float | None:
    dated = [
        (row.trade_date, float(row.external_cash_flow))
        for row in rows
        if row.trade_date <= valuation_date and row.external_cash_flow != ZERO
    ]
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
    rows = list(session.scalars(_transactions_query(portfolio_id, valuation_date).order_by(Transaction.trade_date, Transaction.id)))
    by_ledger: dict[tuple[int, int], list[Transaction]] = {}
    for row in rows:
        if row.security_id is not None:
            by_ledger.setdefault((row.portfolio_id, row.security_id), []).append(row)

    by_security: dict[int, list[LedgerResult]] = {}
    for (_portfolio_id, security_id), ledger_rows in by_ledger.items():
        by_security.setdefault(security_id, []).append(replay_ledger(ledger_rows))

    positions: list[Position] = []
    for security_id, ledgers in by_security.items():
        shares = sum((ledger.shares for ledger in ledgers), ZERO)
        cost_basis = sum((ledger.cost_basis for ledger in ledgers), ZERO)
        realized_profit = sum((ledger.realized_profit for ledger in ledgers), ZERO)
        dividend_income = sum((ledger.dividend_income for ledger in ledgers), ZERO)
        security = session.get(Security, security_id)
        quote = session.scalar(
            select(Quote).where(Quote.security_id == security_id, Quote.market_date <= valuation_date)
            .order_by(Quote.market_date.desc()).limit(1)
        )
        market_value = None if quote is None else shares * quote.close
        positions.append(Position(
            security_id=security_id,
            symbol=security.symbol if security else str(security_id),
            shares=shares,
            cost_basis=cost_basis,
            market_value=market_value,
            realized_profit=realized_profit,
            dividend_income=dividend_income,
            cost_basis_complete=all(ledger.cost_basis_complete for ledger in ledgers),
        ))

    priced_assets = sum((item.market_value or ZERO for item in positions), ZERO)
    cost_basis = sum((item.cost_basis for item in positions), ZERO)
    realized = sum((item.realized_profit for item in positions), ZERO)
    dividends = sum((item.dividend_income for item in positions), ZERO)
    missing_open_value = any(item.shares != ZERO and item.market_value is None for item in positions)
    total_assets = None if missing_open_value else priced_assets
    unrealized = None if total_assets is None else total_assets - cost_basis
    total_profit = None if unrealized is None else unrealized + realized + dividends
    annual = None if total_assets is None else calculate_xirr(rows, total_assets, valuation_date)
    monthly = None if annual is None or annual <= -1 else (1 + annual) ** (1 / 12) - 1
    return PortfolioSummary(total_assets, cost_basis, realized, unrealized, dividends, total_profit, annual, monthly, tuple(positions))


def projection(principal: int | None, years: int = 30, rates: tuple[float, ...] = (0.065, 0.09, 0.115)) -> tuple[tuple[int, ...], ...] | None:
    if principal is None:
        return None
    decimal_principal = Decimal(principal)
    return tuple(
        tuple(
            int(
                (decimal_principal * ((Decimal(1) + Decimal(str(rate))) ** year)).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
            for year in range(years + 1)
        )
        for rate in rates
    )
