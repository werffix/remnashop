from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common.dao import SettingsDao
from src.core.enums import SystemNotificationType


@inject
async def user_types_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()

    types = [
        {
            "type": field.upper(),
            "enabled": value,
        }
        for field, value in settings.notifications.user
    ]

    return {"types": types}


@inject
async def system_types_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()

    types = [
        {
            "type": field.upper(),
            "enabled": value,
        }
        for field, value in settings.notifications.system
        if field != SystemNotificationType.SYSTEM
    ]

    return {"types": types}
