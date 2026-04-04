from datetime import datetime

from adaptix import Retort
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger
from sqlalchemy.exc import IntegrityError

from src.application.common import Notifier
from src.application.common.dao import PromocodeDao
from src.application.common.uow import UnitOfWork
from src.application.dto.promocode import PromocodeDto
from src.application.dto.user import UserDto
from src.core.constants import USER_KEY
from src.core.constants import TIMEZONE
from src.telegram.states import DashboardPromocodes


def _parse_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    if normalized.lower() in {"0", "нет", "none", "null", "-"}:
        return None

    formats = ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%d.%m.%Y", "%d.%m.%Y %H:%M")
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=TIMEZONE)
        except ValueError:
            continue

    raise ValueError(f"Invalid datetime format: {value}")


@inject
async def on_promocode_create(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    promocode = PromocodeDto(
        code=f"PROMO{datetime.now().strftime('%m%d%H%M%S')}",
        discount_percent=10,
        max_activations=None,
        max_activations_per_user=1,
        expires_at=None,
        is_active=True,
    )
    dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)
    await dialog_manager.switch_to(DashboardPromocodes.CONFIGURATOR)


@inject
async def on_promocode_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    promocode_dao: FromDishka[PromocodeDao],
) -> None:
    promocode_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]
    promocode = await promocode_dao.get_by_id(promocode_id)
    if not promocode:
        raise ValueError(f"Promocode '{promocode_id}' not found")
    dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)
    await dialog_manager.switch_to(DashboardPromocodes.CONFIGURATOR)


@inject
async def on_promocode_toggle_active(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    promocode = retort.load(dialog_manager.dialog_data[PromocodeDto.__name__], PromocodeDto)
    promocode.is_active = not promocode.is_active
    dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)


@inject
async def on_promocode_save(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    uow: FromDishka[UnitOfWork],
    promocode_dao: FromDishka[PromocodeDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    promocode = retort.load(dialog_manager.dialog_data[PromocodeDto.__name__], PromocodeDto)
    promocode.code = promocode.code.strip().upper()

    try:
        async with uow:
            if promocode.id:
                await promocode_dao.update(promocode)
                await notifier.notify_user(user, i18n_key="ntf-promocode.updated")
            else:
                created = await promocode_dao.create(promocode)
                dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(created)
                await notifier.notify_user(user, i18n_key="ntf-promocode.created")
            await uow.commit()
    except IntegrityError:
        logger.warning(f"{user.log} Failed to save promocode '{promocode.code}' due to duplicate code")
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    await dialog_manager.start(DashboardPromocodes.MAIN, mode=StartMode.RESET_STACK)


@inject
async def on_promocode_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    uow: FromDishka[UnitOfWork],
    promocode_dao: FromDishka[PromocodeDao],
    notifier: FromDishka[Notifier],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    promocode = retort.load(dialog_manager.dialog_data[PromocodeDto.__name__], PromocodeDto)
    if not promocode.id:
        await dialog_manager.start(DashboardPromocodes.MAIN, mode=StartMode.RESET_STACK)
        return

    async with uow:
        await promocode_dao.delete(promocode.id)
        await uow.commit()

    await notifier.notify_user(user, i18n_key="ntf-promocode.deleted")
    await dialog_manager.start(DashboardPromocodes.MAIN, mode=StartMode.RESET_STACK)


@inject
async def on_promocode_code_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    promocode = retort.load(dialog_manager.dialog_data[PromocodeDto.__name__], PromocodeDto)
    promocode.code = message.text.strip().upper()
    dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)
    await dialog_manager.switch_to(DashboardPromocodes.CONFIGURATOR)


@inject
async def on_promocode_discount_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    if not message.text or not message.text.isdigit():
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    discount = int(message.text)
    if discount <= 0 or discount > 100:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    promocode = retort.load(dialog_manager.dialog_data[PromocodeDto.__name__], PromocodeDto)
    promocode.discount_percent = discount
    dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)
    await dialog_manager.switch_to(DashboardPromocodes.CONFIGURATOR)


@inject
async def on_promocode_limit_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    raw_value = message.text.strip().lower()
    if raw_value in {"0", "нет", "none", "null", "-"}:
        limit = None
    elif raw_value.isdigit() and int(raw_value) > 0:
        limit = int(raw_value)
    else:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    promocode = retort.load(dialog_manager.dialog_data[PromocodeDto.__name__], PromocodeDto)
    promocode.max_activations = limit
    dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)
    await dialog_manager.switch_to(DashboardPromocodes.CONFIGURATOR)


@inject
async def on_promocode_per_user_limit_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    raw_value = message.text.strip().lower()
    if raw_value in {"0", "нет", "none", "null", "-"}:
        limit = None
    elif raw_value.isdigit() and int(raw_value) > 0:
        limit = int(raw_value)
    else:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    promocode = retort.load(dialog_manager.dialog_data[PromocodeDto.__name__], PromocodeDto)
    promocode.max_activations_per_user = limit
    dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)
    await dialog_manager.switch_to(DashboardPromocodes.CONFIGURATOR)


@inject
async def on_promocode_expires_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    try:
        expires_at = _parse_datetime(message.text)
    except ValueError as e:
        logger.warning(str(e))
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    promocode = retort.load(dialog_manager.dialog_data[PromocodeDto.__name__], PromocodeDto)
    promocode.expires_at = expires_at
    dialog_manager.dialog_data[PromocodeDto.__name__] = retort.dump(promocode)
    await dialog_manager.switch_to(DashboardPromocodes.CONFIGURATOR)
