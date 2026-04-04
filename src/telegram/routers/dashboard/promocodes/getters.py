from datetime import datetime
from typing import Any

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common.dao import PromocodeDao
from src.application.dto.promocode import PromocodeDto


def _format_datetime(value: datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else "Не ограничено"


@inject
async def promocodes_getter(
    dialog_manager: DialogManager,
    promocode_dao: FromDishka[PromocodeDao],
    **kwargs: Any,
) -> dict[str, Any]:
    promocodes = await promocode_dao.get_all()
    formatted = []
    for promocode in promocodes:
        activations = await promocode_dao.count_activations(promocode.id)  # type: ignore[arg-type]
        formatted.append(
            {
                "id": promocode.id,
                "code": promocode.code,
                "is_active": promocode.is_active,
                "activations": activations,
            }
        )

    return {"promocodes": formatted}


@inject
async def promocode_configurator_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    promocode_dao: FromDishka[PromocodeDao],
    **kwargs: Any,
) -> dict[str, Any]:
    raw_promocode = dialog_manager.dialog_data.get(PromocodeDto.__name__)
    if raw_promocode is None:
        promocode = PromocodeDto(
            code="PROMO10",
            discount_percent=10,
            max_activations=None,
            max_activations_per_user=1,
            expires_at=None,
            is_active=True,
        )
        dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)
    else:
        promocode = retort.load(raw_promocode, PromocodeDto)

    activations = 0
    if promocode.id:
        activations = await promocode_dao.count_activations(promocode.id)

    return {
        "code": promocode.code,
        "discount_percent": promocode.discount_percent,
        "max_activations": promocode.max_activations if promocode.max_activations else "Не ограничено",
        "max_activations_per_user": (
            promocode.max_activations_per_user
            if promocode.max_activations_per_user
            else "Не ограничено"
        ),
        "expires_at": _format_datetime(promocode.expires_at),
        "is_active": promocode.is_active,
        "activations": activations,
        "is_edit": bool(promocode.id),
    }
