"""CRUD and reporting helpers for the small Personal Finance page."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..exceptions import ValidationError
from ..models import AnnualFinanceSnapshot, MonthlyFinanceRecord


@dataclass(frozen=True, slots=True)
class MonthlyFinanceInput:
    year: int
    month: int
    income: int | None = None
    expenditure: int | None = None


@dataclass(frozen=True, slots=True)
class AnnualFinanceInput:
    year: int
    total_asset_excluding_investment: int | None = None
    total_portfolio_value: int | None = None
    total_debt: int | None = None


@dataclass(frozen=True, slots=True)
class YearlyFinanceSummary:
    """Independent income/expenditure totals and their reporting coverage."""

    year: int
    income: int | None
    expenditure: int | None
    surplus: int | None


@dataclass(frozen=True, slots=True)
class YearlyFinanceRow:
    """A yearly manual snapshot paired with monthly-derived totals."""

    snapshot: AnnualFinanceSnapshot
    summary: YearlyFinanceSummary

    @property
    def net_worth(self) -> int | None:
        values = (
            self.snapshot.total_asset_excluding_investment,
            self.snapshot.total_portfolio_value,
            self.snapshot.total_debt,
        )
        if any(value is None for value in values):
            return None
        assets, portfolio, debt = values
        assert assets is not None and portfolio is not None and debt is not None
        return assets + portfolio - debt


def _integer(value: object, field: str, *, allow_none: bool = False) -> int | None:
    if value is None or (allow_none and isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise ValidationError(f"{field} is required.")
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be a whole number.")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValidationError(f"{field} must be a whole number.") from error
    if not number.is_finite() or number != number.to_integral_value():
        raise ValidationError(f"{field} must be a whole number.")
    return int(number)


def _nonnegative(value: object, field: str) -> int | None:
    result = _integer(value, field, allow_none=True)
    if result is not None and result < 0:
        raise ValidationError(f"{field} cannot be negative.")
    return result


def _year(value: object) -> int:
    result = _integer(value, "Year")
    assert result is not None
    if not 1 <= result <= 9999:
        raise ValidationError("Year must be between 1 and 9999.")
    return result


def _month(value: object) -> int:
    result = _integer(value, "Month")
    assert result is not None
    if not 1 <= result <= 12:
        raise ValidationError("Month must be between 1 and 12.")
    return result


def normalize_monthly_input(data: MonthlyFinanceInput) -> MonthlyFinanceInput:
    if not isinstance(data, MonthlyFinanceInput):
        raise ValidationError("Monthly finance data is invalid.")
    return MonthlyFinanceInput(
        year=_year(data.year),
        month=_month(data.month),
        income=_nonnegative(data.income, "Income"),
        expenditure=_nonnegative(data.expenditure, "Expenditure"),
    )


def normalize_annual_input(data: AnnualFinanceInput) -> AnnualFinanceInput:
    if not isinstance(data, AnnualFinanceInput):
        raise ValidationError("Annual finance data is invalid.")
    return AnnualFinanceInput(
        year=_year(data.year),
        total_asset_excluding_investment=_nonnegative(
            data.total_asset_excluding_investment,
            "Total assets excluding investment",
        ),
        total_portfolio_value=_nonnegative(
            data.total_portfolio_value, "Total portfolio value"
        ),
        total_debt=_nonnegative(data.total_debt, "Total debt"),
    )


def upsert_monthly_record(
    session: Session, data: MonthlyFinanceInput
) -> MonthlyFinanceRecord:
    """Insert or replace the row identified by ``(year, month)``."""

    data = normalize_monthly_input(data)
    record = session.scalar(
        select(MonthlyFinanceRecord).where(
            MonthlyFinanceRecord.year == data.year,
            MonthlyFinanceRecord.month == data.month,
        )
    )
    if record is None:
        record = MonthlyFinanceRecord(year=data.year, month=data.month)
        session.add(record)
    record.income = data.income
    record.expenditure = data.expenditure
    session.flush()
    return record


def get_monthly_record(
    session: Session, year: int, month: int
) -> MonthlyFinanceRecord | None:
    return session.scalar(
        select(MonthlyFinanceRecord).where(
            MonthlyFinanceRecord.year == _year(year),
            MonthlyFinanceRecord.month == _month(month),
        )
    )


def list_monthly_records(
    session: Session, year: int | None = None
) -> list[MonthlyFinanceRecord]:
    statement = select(MonthlyFinanceRecord)
    if year is not None:
        statement = statement.where(MonthlyFinanceRecord.year == _year(year))
    statement = statement.order_by(
        MonthlyFinanceRecord.year, MonthlyFinanceRecord.month
    )
    return list(session.scalars(statement))


def delete_monthly_record(session: Session, year: int, month: int) -> bool:
    record = get_monthly_record(session, year, month)
    if record is None:
        return False
    session.delete(record)
    session.flush()
    return True


def upsert_annual_snapshot(
    session: Session, data: AnnualFinanceInput
) -> AnnualFinanceSnapshot:
    """Insert or replace the manually entered snapshot for a year."""

    data = normalize_annual_input(data)
    record = session.scalar(
        select(AnnualFinanceSnapshot).where(AnnualFinanceSnapshot.year == data.year)
    )
    if record is None:
        record = AnnualFinanceSnapshot(year=data.year)
        session.add(record)
    record.total_asset_excluding_investment = data.total_asset_excluding_investment
    record.total_portfolio_value = data.total_portfolio_value
    record.total_debt = data.total_debt
    session.flush()
    return record


def get_annual_snapshot(session: Session, year: int) -> AnnualFinanceSnapshot | None:
    return session.scalar(
        select(AnnualFinanceSnapshot).where(AnnualFinanceSnapshot.year == _year(year))
    )


def list_annual_snapshots(session: Session) -> list[AnnualFinanceSnapshot]:
    return list(
        session.scalars(
            select(AnnualFinanceSnapshot).order_by(AnnualFinanceSnapshot.year)
        )
    )


def calculate_yearly_summary(session: Session, year: int) -> YearlyFinanceSummary:
    """Calculate totals from non-null monthly values for ``year``."""

    year_value = _year(year)
    rows = list_monthly_records(session, year_value)
    income_rows = {row.month: row.income for row in rows if row.income is not None}
    expenditure_rows = {
        row.month: row.expenditure for row in rows if row.expenditure is not None
    }
    income_values = list(income_rows.values())
    expenditure_values = list(expenditure_rows.values())
    income = sum(income_values) if income_values else None
    expenditure = sum(expenditure_values) if expenditure_values else None
    # A surplus is meaningful only when both values cover the same months.
    surplus = (
        income - expenditure
        if income is not None
        and expenditure is not None
        and income_rows.keys() == expenditure_rows.keys()
        else None
    )
    return YearlyFinanceSummary(
        year=year_value,
        income=income,
        expenditure=expenditure,
        surplus=surplus,
    )


def list_yearly_finance_rows(
    session: Session, years: Iterable[int] | None = None
) -> list[YearlyFinanceRow]:
    snapshots = list_annual_snapshots(session)
    wanted = None if years is None else {_year(year) for year in years}
    snapshot_by_year = {row.year: row for row in snapshots}
    monthly_years = {row.year for row in list_monthly_records(session)}
    all_years = set(snapshot_by_year) | monthly_years
    if wanted is not None:
        all_years &= wanted
    result: list[YearlyFinanceRow] = []
    for year in sorted(all_years):
        snapshot = snapshot_by_year.get(year)
        if snapshot is None:
            # Keep a monthly-only year visible until manual fields are entered.
            snapshot = AnnualFinanceSnapshot(year=year)
        result.append(
            YearlyFinanceRow(
                snapshot=snapshot,
                summary=calculate_yearly_summary(session, year),
            )
        )
    return result
