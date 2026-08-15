from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
    __table_args__ = (
        UniqueConstraint("provider", "symbol", name="uq_security_provider_symbol"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), default="FinMind", nullable=False)
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
        CheckConstraint("trade_amount >= 0", name="ck_transaction_trade_nonnegative"),
        CheckConstraint("income_amount >= 0", name="ck_transaction_income_nonnegative"),
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
    external_cash_flow: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trade_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    income_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        UniqueConstraint(
            "security_id", "provider", "market_date", name="uq_quote_security_day"
        ),
        CheckConstraint("close > 0", name="ck_quote_positive"),
        Index("ix_quotes_security_date", "security_id", "market_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), default="FinMind", nullable=False)
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    refresh_cycle_date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    security: Mapped[Security] = relationship()


class TransactionAudit(Base):
    __tablename__ = "transaction_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SchemaMeta(Base):
    __tablename__ = "schema_meta"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(240), nullable=False)


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
