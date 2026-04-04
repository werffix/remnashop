from aiogram.enums import ButtonStyle
from aiogram_dialog import Dialog, StartMode, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Column, ListGroup, Row, Start, SwitchTo
from aiogram_dialog.widgets.style import Style
from magic_filter import F

from src.core.enums import BannerName
from src.telegram.keyboards import main_menu_button
from src.telegram.states import Dashboard, DashboardPromocodes
from src.telegram.widgets import Banner, I18nFormat, IgnoreUpdate

from .getters import promocode_configurator_getter, promocodes_getter
from .handlers import (
    on_promocode_code_input,
    on_promocode_create,
    on_promocode_delete,
    on_promocode_discount_input,
    on_promocode_expires_input,
    on_promocode_limit_input,
    on_promocode_save,
    on_promocode_select,
    on_promocode_toggle_active,
)


main = Window(
    Banner(BannerName.PROMOCODE),
    I18nFormat("msg-promocodes-list"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocodes.my"),
            id="my_promocodes",
            state=DashboardPromocodes.MAIN,
        ),
        Button(
            text=I18nFormat("btn-promocodes.create"),
            id="create_promocode",
            on_click=on_promocode_create,
        ),
    ),
    Column(
        ListGroup(
            Row(
                Button(
                    text=I18nFormat(
                        "btn-promocodes.title",
                        code=F["item"]["code"],
                        is_active=F["item"]["is_active"],
                    ),
                    id="select_promocode",
                    on_click=on_promocode_select,
                ),
            ),
            id="promocodes_list",
            item_id_getter=lambda item: item["id"],
            items="promocodes",
        ),
    ),
    Row(
        Start(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=Dashboard.MAIN,
            mode=StartMode.RESET_STACK,
        ),
        *main_menu_button,
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.MAIN,
    getter=promocodes_getter,
)

configurator = Window(
    Banner(BannerName.PROMOCODE),
    I18nFormat("msg-promocode-configurator"),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.active", is_active=F["is_active"]),
            id="toggle_active",
            on_click=on_promocode_toggle_active,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocodes.code"),
            id="code",
            state=DashboardPromocodes.CODE,
        ),
        SwitchTo(
            text=I18nFormat("btn-promocodes.discount"),
            id="discount",
            state=DashboardPromocodes.REWARD,
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-promocodes.limit"),
            id="limit",
            state=DashboardPromocodes.ALLOWED,
        ),
        SwitchTo(
            text=I18nFormat("btn-promocodes.expires"),
            id="expires",
            state=DashboardPromocodes.LIFETIME,
        ),
    ),
    Row(
        Button(
            text=I18nFormat("btn-promocodes.save"),
            id="save_promocode",
            on_click=on_promocode_save,
            style=Style(ButtonStyle.SUCCESS),
        ),
        Button(
            text=I18nFormat("btn-promocodes.delete"),
            id="delete_promocode",
            on_click=on_promocode_delete,
            style=Style(ButtonStyle.DANGER),
            when=F["is_edit"],
        ),
    ),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.MAIN,
        ),
    ),
    IgnoreUpdate(),
    state=DashboardPromocodes.CONFIGURATOR,
    getter=promocode_configurator_getter,
)

code = Window(
    Banner(BannerName.PROMOCODE),
    I18nFormat("msg-promocode-code"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_promocode_code_input),
    IgnoreUpdate(),
    state=DashboardPromocodes.CODE,
)

discount = Window(
    Banner(BannerName.PROMOCODE),
    I18nFormat("msg-promocode-discount"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_promocode_discount_input),
    IgnoreUpdate(),
    state=DashboardPromocodes.REWARD,
)

limit = Window(
    Banner(BannerName.PROMOCODE),
    I18nFormat("msg-promocode-limit"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_promocode_limit_input),
    IgnoreUpdate(),
    state=DashboardPromocodes.ALLOWED,
)

expires = Window(
    Banner(BannerName.PROMOCODE),
    I18nFormat("msg-promocode-expires"),
    Row(
        SwitchTo(
            text=I18nFormat("btn-back.general"),
            id="back",
            state=DashboardPromocodes.CONFIGURATOR,
        ),
    ),
    MessageInput(func=on_promocode_expires_input),
    IgnoreUpdate(),
    state=DashboardPromocodes.LIFETIME,
)

router = Dialog(main, configurator, code, discount, limit, expires)
