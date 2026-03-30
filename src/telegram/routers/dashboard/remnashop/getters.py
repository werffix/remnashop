from typing import Any

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.dto import UserDto
from src.application.common.dao import SettingsDao
from src.application.use_cases.user.commands.roles import GetAdmins, GetAdminsResultDto
from src.core.config import AppConfig


async def remnashop_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    **kwargs: Any,
) -> dict[str, Any]:
    return {"version": config.build.tag}


@inject
async def admins_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    retort: FromDishka[Retort],
    get_admins: FromDishka[GetAdmins],
    **kwargs: Any,
) -> dict[str, Any]:
    admins = await get_admins(user)
    return {"admins": retort.dump(admins, list[GetAdminsResultDto])}


@inject
async def trial_period_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    return {"trial_days": settings.access.trial_days}
