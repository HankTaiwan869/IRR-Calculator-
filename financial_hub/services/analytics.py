from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pyxirr import xirr
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..models import Portfolio, Quote, Security, Transaction, TransactionKind

ZERO = 0
MONEY_ZERO = Decimal(0)
MONEY_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class LedgerResult:
    """Share and paid-dividend totals for one security ledger."""

    shares: int
    dividend_income: int
    opening_position_complete: bool


def replay_ledger(rows: Iterable[Transaction]) -> LedgerResult:
    shares = dividends = ZERO
    opening_complete = True
    for row in sorted(rows, key=lambda item: (item.trade_date, item.id or 0)):
        kind = TransactionKind(row.kind)
        if kind in (
            TransactionKind.BUY,
            TransactionKind.REINVESTED_DIVIDEND,
            TransactionKind.OPENING_POSITION,
        ):
            shares += row.shares_delta
            # Existing databases may contain an opening position with no
            # historical investment; total profit/IRR are then indeterminate.
            if kind is TransactionKind.OPENING_POSITION and row.amount >= ZERO:
                opening_complete = False
        elif kind is TransactionKind.SELL:
            shares += row.shares_delta
        elif kind is TransactionKind.DIVIDEND:
            dividends += row.amount
    return LedgerResult(
        shares=shares,
        dividend_income=dividends,
        opening_position_complete=opening_complete,
    )


@dataclass(frozen=True, slots=True)
class Position:
    security_id: int
    symbol: str
    shares: int
    market_value: Decimal | None
    dividend_income: int


@dataclass(frozen=True, slots=True)
class PortfolioSummary:
    total_assets: Decimal | None
    dividend_income: int
    total_profit: Decimal | None
    annual_irr: float | None
    monthly_irr: float | None
    positions: tuple[Position, ...]


def _transactions_query(
    portfolio_id: int | None, valuation_date: date
) -> Select[tuple[Transaction]]:
    query = select(Transaction).where(Transaction.trade_date <= valuation_date)
    if portfolio_id is None:
        return query.join(Portfolio, Transaction.portfolio_id == Portfolio.id).where(
            Portfolio.archived_at.is_(None)
        )
    return query.where(Transaction.portfolio_id == portfolio_id)


def calculate_xirr(
    rows: list[Transaction], terminal_value: Decimal | int, valuation_date: date
) -> float | None:
    dated: list[tuple[date, Decimal]] = [
        (row.trade_date, Decimal(str(row.amount)))
        for row in rows
        if row.trade_date <= valuation_date and row.amount != ZERO
    ]
    terminal = Decimal(str(terminal_value))
    if terminal != MONEY_ZERO:
        dated.append((valuation_date, terminal))
    values = [amount for _, amount in dated]
    if (
        not dated
        or not any(value < 0 for value in values)
        or not any(value > 0 for value in values)
    ):
        return None
    try:
        # pyxirr accepts numeric floats; keep all values exact until this API
        # boundary so fractional quote prices are not lost in the ledger.
        result = xirr(
            [day for day, _ in dated], [float(value) for value in values]
        )
        return None if result is None else float(result)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        return None


def portfolio_summary(
    session: Session, valuation_date: date, portfolio_id: int | None = None
) -> PortfolioSummary:
    rows = list(
        session.scalars(
            _transactions_query(portfolio_id, valuation_date).order_by(
                Transaction.trade_date, Transaction.id
            )
        )
    )
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
        dividends = sum((ledger.dividend_income for ledger in ledgers), ZERO)
        security = session.get(Security, security_id)
        quote = session.scalar(
            select(Quote)
            .where(
                Quote.security_id == security_id, Quote.market_date <= valuation_date
            )
            .order_by(Quote.market_date.desc())
            .limit(1)
        )
        market_value = (
            None
            if quote is None
            else Decimal(shares) * Decimal(str(quote.close))
        )
        positions.append(
            Position(
                security_id=security_id,
                symbol=security.symbol if security else str(security_id),
                shares=shares,
                market_value=market_value,
                dividend_income=dividends,
            )
        )

    priced_assets = sum(
        (item.market_value for item in positions if item.market_value is not None),
        MONEY_ZERO,
    )
    missing_open_value = any(
        item.shares != ZERO and item.market_value is None for item in positions
    )
    total_assets = None if missing_open_value else priced_assets
    opening_complete = all(
        ledger.opening_position_complete
        for ledgers in by_security.values()
        for ledger in ledgers
    )
    dividends = sum(
        (
            row.amount
            for row in rows
            if TransactionKind(row.kind) is TransactionKind.DIVIDEND
        ),
        ZERO,
    )
    total_profit = (
        None
        if total_assets is None or not opening_complete
        else total_assets
        + sum((Decimal(str(row.amount)) for row in rows), MONEY_ZERO)
    )
    annual = (
        None
        if total_assets is None or not opening_complete
        else calculate_xirr(rows, total_assets, valuation_date)
    )
    monthly = None if annual is None or annual <= -1 else (1 + annual) ** (1 / 12) - 1
    return PortfolioSummary(
        total_assets,
        dividends,
        total_profit,
        annual,
        monthly,
        tuple(positions),
    )


def projection(
    principal: Decimal | int | None,
    years: int = 30,
    rates: tuple[Decimal | float, ...] = (0.065, 0.09, 0.115),
) -> tuple[tuple[Decimal, ...], ...] | None:
    if principal is None:
        return None
    decimal_principal = Decimal(str(principal))
    return tuple(
        tuple(
            decimal_principal
            * ((MONEY_ONE + Decimal(str(rate))) ** year)
            for year in range(years + 1)
        )
        for rate in rates
    )
