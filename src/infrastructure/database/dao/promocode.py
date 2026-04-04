from typing import Optional, cast
from uuid import UUID

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.common.dao import PromocodeDao
from src.application.dto.promocode import PromocodeDto
from src.infrastructure.database.models import Promocode, PromocodeActivation

from .base import BaseDaoImpl


class PromocodeDaoImpl(PromocodeDao, BaseDaoImpl):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
        redis: Redis,
    ) -> None:
        super().__init__(session, retort)
        self.conversion_retort = conversion_retort
        self.redis = redis

        self._convert_to_dto = self.conversion_retort.get_converter(Promocode, PromocodeDto)
        self._convert_to_dto_list = self.conversion_retort.get_converter(
            list[Promocode],
            list[PromocodeDto],
        )

    async def create(self, promocode: PromocodeDto) -> PromocodeDto:
        db_promocode = Promocode(**self.retort.dump(promocode))
        self.session.add(db_promocode)
        await self.session.flush()
        logger.debug(f"Created promocode '{promocode.code}'")
        return self._convert_to_dto(db_promocode)

    async def get_by_id(self, promocode_id: int) -> Optional[PromocodeDto]:
        stmt = select(Promocode).where(Promocode.id == promocode_id)
        db_promocode = await self.session.scalar(stmt)
        return self._convert_to_dto(db_promocode) if db_promocode else None

    async def get_by_code(self, code: str) -> Optional[PromocodeDto]:
        stmt = select(Promocode).where(func.lower(Promocode.code) == code.lower())
        db_promocode = await self.session.scalar(stmt)
        return self._convert_to_dto(db_promocode) if db_promocode else None

    async def get_all(self) -> list[PromocodeDto]:
        stmt = select(Promocode).order_by(Promocode.id.desc())
        result = await self.session.scalars(stmt)
        db_promocodes = cast(list[Promocode], result.all())
        return self._convert_to_dto_list(db_promocodes)

    async def update(self, promocode: PromocodeDto) -> Optional[PromocodeDto]:
        if not promocode.changed_data:
            return promocode

        values_to_update = self._serialize_for_update(promocode, PromocodeDto, Promocode)
        stmt = (
            update(Promocode)
            .where(Promocode.id == promocode.id)
            .values(**values_to_update)
            .returning(Promocode)
        )
        db_promocode = await self.session.scalar(stmt)
        if not db_promocode:
            return None
        return self._convert_to_dto(db_promocode)

    async def delete(self, promocode_id: int) -> bool:
        stmt = delete(Promocode).where(Promocode.id == promocode_id).returning(Promocode.id)
        deleted_id = await self.session.scalar(stmt)
        return deleted_id is not None

    async def count_activations(self, promocode_id: int) -> int:
        stmt = select(func.count(PromocodeActivation.id)).where(
            PromocodeActivation.promocode_id == promocode_id
        )
        return int(await self.session.scalar(stmt) or 0)

    async def has_user_activation(self, promocode_id: int, user_telegram_id: int) -> bool:
        stmt = select(func.count(PromocodeActivation.id)).where(
            PromocodeActivation.promocode_id == promocode_id,
            PromocodeActivation.user_telegram_id == user_telegram_id,
        )
        return bool(await self.session.scalar(stmt) or 0)

    async def create_activation(
        self,
        promocode_id: int,
        user_telegram_id: int,
        transaction_payment_id: Optional[UUID] = None,
    ) -> None:
        self.session.add(
            PromocodeActivation(
                promocode_id=promocode_id,
                user_telegram_id=user_telegram_id,
                transaction_payment_id=transaction_payment_id,
            )
        )
        await self.session.flush()
