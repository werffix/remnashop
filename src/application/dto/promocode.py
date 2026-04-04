from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID

from .base import BaseDto, TimestampMixin, TrackableMixin


@dataclass(kw_only=True)
class PromocodeDto(BaseDto, TrackableMixin, TimestampMixin):
    code: str
    discount_percent: int
    max_activations: Optional[int] = None
    max_activations_per_user: Optional[int] = 1
    expires_at: Optional[datetime] = None
    is_active: bool = True


@dataclass(kw_only=True)
class PromocodeActivationDto(BaseDto, TimestampMixin):
    promocode_id: int
    user_telegram_id: int
    transaction_payment_id: Optional[UUID] = None
