from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseSql
from .timestamp import TimestampMixin


class Promocode(BaseSql, TimestampMixin):
    __tablename__ = "promocodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    discount_percent: Mapped[int]
    max_activations: Mapped[Optional[int]]
    expires_at: Mapped[Optional[datetime]]
    is_active: Mapped[bool]


class PromocodeActivation(BaseSql, TimestampMixin):
    __tablename__ = "promocode_activations"

    id: Mapped[int] = mapped_column(primary_key=True)
    promocode_id: Mapped[int] = mapped_column(ForeignKey("promocodes.id", ondelete="CASCADE"))
    user_telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        index=True,
    )
    transaction_payment_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("transactions.payment_id", ondelete="SET NULL"),
        nullable=True,
    )
