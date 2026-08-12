from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Security


def search_securities(session: Session, query: str, exchange: str | None = None, security_type: str | None = None, limit: int = 50) -> list[Security]:
    text = query.strip()
    statement = select(Security).where(Security.active.is_(True))
    if text:
        escaped = text.replace("%", r"\%").replace("_", r"\_")
        pattern = f"%{escaped}%"
        statement = statement.where(or_(Security.symbol.ilike(pattern, escape="\\"), Security.name_zh.ilike(pattern, escape="\\")))
    if exchange:
        statement = statement.where(Security.exchange == exchange)
    if security_type:
        statement = statement.where(Security.security_type == security_type)
    return list(session.scalars(statement.order_by(Security.symbol).limit(limit)))
