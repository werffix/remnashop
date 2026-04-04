from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from src.application.dto.promocode import PromocodeDto


@runtime_checkable
class PromocodeDao(Protocol):
    async def create(self, promocode: PromocodeDto) -> PromocodeDto: ...

    async def get_by_id(self, promocode_id: int) -> Optional[PromocodeDto]: ...

    async def get_by_code(self, code: str) -> Optional[PromocodeDto]: ...

    async def get_all(self) -> list[PromocodeDto]: ...

    async def update(self, promocode: PromocodeDto) -> Optional[PromocodeDto]: ...

    async def delete(self, promocode_id: int) -> bool: ...

    async def count_activations(self, promocode_id: int) -> int: ...

    async def has_user_activation(self, promocode_id: int, user_telegram_id: int) -> bool: ...

    async def create_activation(
        self,
        promocode_id: int,
        user_telegram_id: int,
        transaction_payment_id: Optional[UUID] = None,
    ) -> None: ...
