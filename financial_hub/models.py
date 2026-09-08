from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TransactionKind(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    REINVESTED_DIVIDEND = "REINVESTED_DIVIDEND"
    OPENING_POSITION = "OPENING_POSITION"
    POSITION_RECONCILIATION = "POSITION_RECONCILIATION"
    LEGACY_CASH_FLOW = "LEGACY_CASH_FLOW"


class Portfolio(Base):
    __tablename__ = "portfolios"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    transactions: Mapped[list[Transaction]] = relationship(back_populates="portfolio")


class Security(Base):
    __tablename__ = "securities"
    __table_args__ = (UniqueConstraint("symbol", name="uq_security_symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name_zh: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    security_type: Mapped[str] = mapped_column(
        String(32), default="stock", nullable=False
    )
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_portfolio_date", "portfolio_id", "trade_date", "id"),
        Index("ix_transactions_security_date", "security_id", "trade_date", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id"), nullable=False
    )
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id"))
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    shares_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Signed owner cash flow: buys are negative, sales/dividends positive.
    # Reinvested dividends have amount zero because they never cross the
    # portfolio boundary.  Opening positions use a negative deemed investment.
    amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")
    security: Mapped[Security | None] = relationship()


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("security_id", "market_date", name="uq_quote_security_day"),
        CheckConstraint("close > 0", name="ck_quote_positive"),
        Index("ix_quotes_security_date", "security_id", "market_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id"), nullable=False
    )
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    refresh_cycle_date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    security: Mapped[Security] = relationship()


class MonthlyFinanceRecord(Base):
    """One manually maintained income/expenditure entry for a calendar month.

    Income and expenditure are deliberately nullable.  A null value means the
    month has not been reported yet, while zero is a real reported value.  The
    app stores expenditure as a positive number, matching the personal
    finance page's input convention.
    """

    __tablename__ = "personal_finance_monthly"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_personal_finance_month"),
        CheckConstraint("year BETWEEN 1 AND 9999", name="ck_personal_finance_year"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_personal_finance_month"),
        CheckConstraint(
            "income IS NULL OR income >= 0", name="ck_personal_finance_income"
        ),
        CheckConstraint(
            "expenditure IS NULL OR expenditure >= 0",
            name="ck_personal_finance_expenditure",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    income: Mapped[int | None] = mapped_column(Integer)
    expenditure: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AnnualFinanceSnapshot(Base):
    """The three manually entered annual personal-finance values.

    ``total_asset_excluding_investment`` contains cash and other
    non-investment assets.  ``total_portfolio_value`` is kept separate so a
    portfolio price refresh cannot silently change a saved snapshot.
    """

    __tablename__ = "personal_finance_annual"
    __table_args__ = (
        UniqueConstraint("year", name="uq_personal_finance_annual_year"),
        CheckConstraint(
            "year BETWEEN 1 AND 9999", name="ck_personal_finance_annual_year"
        ),
        CheckConstraint(
            "total_asset_excluding_investment IS NULL OR total_asset_excluding_investment >= 0",
            name="ck_personal_finance_assets_nonnegative",
        ),
        CheckConstraint(
            "total_portfolio_value IS NULL OR total_portfolio_value >= 0",
            name="ck_personal_finance_portfolio_nonnegative",
        ),
        CheckConstraint(
            "total_debt IS NULL OR total_debt >= 0",
            name="ck_personal_finance_debt_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    total_asset_excluding_investment: Mapped[int | None] = mapped_column(Integer)
    total_portfolio_value: Mapped[int | None] = mapped_column(Integer)
    total_debt: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
