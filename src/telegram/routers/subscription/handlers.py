from typing import Optional, TypedDict, cast

from adaptix import Retort
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier
from src.application.common.dao import (
    PaymentGatewayDao,
    PlanDao,
    PromocodeDao,
    SettingsDao,
    SubscriptionDao,
)
from src.application.dto import MessagePayloadDto, PaymentGatewayDto, PlanDto, PlanSnapshotDto, UserDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.application.services import PricingService
from src.application.use_cases.gateways.commands.payment import (
    CreatePayment,
    CreatePaymentDto,
    ProcessPayment,
    ProcessPaymentDto,
)
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.constants import PAYMENT_PREFIX, USER_KEY
from src.core.enums import PaymentGatewayType, PlanAvailability, PurchaseType, TransactionStatus
from src.core.utils.time import datetime_now
from src.telegram.states import Subscription

PAYMENT_CACHE_KEY = "payment_cache"
CURRENT_DURATION_KEY = "selected_duration"
CURRENT_METHOD_KEY = "selected_payment_method"
CURRENT_METHOD_OPTION_KEY = "selected_payment_method_option"
CURRENT_PLATEGA_METHOD_KEY = "selected_platega_payment_method"
CURRENT_PROMOCODE_ID_KEY = "selected_promocode_id"
CURRENT_PROMOCODE_DISCOUNT_KEY = "selected_promocode_discount"
Q1_SUPPORT_URL = "https://t.me/q1support_bot"


class CachedPaymentData(TypedDict):
    payment_id: str
    payment_url: Optional[str]
    final_pricing: str


def _get_cache_key(duration: int, payment_option: str) -> str:
    return f"{duration}:{payment_option}"


def _serialize_payment_option(
    gateway_type: PaymentGatewayType,
    platega_payment_method: Optional[int] = None,
) -> str:
    if platega_payment_method is None:
        return gateway_type.value
    return f"{gateway_type.value}:{platega_payment_method}"


def _parse_payment_option(value: str) -> tuple[PaymentGatewayType, Optional[int]]:
    gateway_raw, _, method_raw = value.partition(":")
    payment_method = int(method_raw) if method_raw else None
    return PaymentGatewayType(gateway_raw), payment_method


def _load_payment_data(dialog_manager: DialogManager) -> dict[str, CachedPaymentData]:
    if PAYMENT_CACHE_KEY not in dialog_manager.dialog_data:
        dialog_manager.dialog_data[PAYMENT_CACHE_KEY] = {}
    return cast(dict[str, CachedPaymentData], dialog_manager.dialog_data[PAYMENT_CACHE_KEY])


def _get_promocode_discount(dialog_manager: DialogManager) -> int:
    return int(dialog_manager.dialog_data.get(CURRENT_PROMOCODE_DISCOUNT_KEY, 0) or 0)


async def _notify_topup_support(callback: CallbackQuery, text: str) -> None:
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Перейти", url=Q1_SUPPORT_URL)],
        ]
    )

    if callback.message:
        await callback.message.answer(text=text, reply_markup=keyboard)
    await callback.answer()


def _hydrate_dialog_data_from_start_data(dialog_manager: DialogManager) -> None:
    start_data = dialog_manager.start_data
    if not isinstance(start_data, dict):
        return

    for key, value in start_data.items():
        dialog_manager.dialog_data.setdefault(key, value)


def _get_payment_options(gateways: list[PaymentGatewayDto]) -> list[str]:
    options: list[str] = []

    for gateway in gateways:
        if gateway.type == PaymentGatewayType.PLATEGA and isinstance(
            gateway.settings, PlategaGatewaySettingsDto
        ):
            methods = gateway.settings.payment_methods
            if methods:
                options.extend(_serialize_payment_option(gateway.type, method) for method in methods)
            continue

        options.append(_serialize_payment_option(gateway.type))

    return options


def _save_payment_data(dialog_manager: DialogManager, payment_data: CachedPaymentData) -> None:
    dialog_manager.dialog_data["payment_id"] = payment_data["payment_id"]
    dialog_manager.dialog_data["payment_url"] = payment_data["payment_url"]
    dialog_manager.dialog_data["final_pricing"] = payment_data["final_pricing"]


async def _create_payment_and_get_data(
    dialog_manager: DialogManager,
    plan: PlanDto,
    duration_days: int,
    gateway_type: PaymentGatewayType,
    retort: Retort,
    payment_gateway_dao: PaymentGatewayDao,
    notifier: Notifier,
    pricing_service: PricingService,
    create_payment: CreatePayment,
    platega_payment_method: Optional[int] = None,
) -> Optional[CachedPaymentData]:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    duration = plan.get_duration(duration_days)
    payment_gateway = await payment_gateway_dao.get_by_type(gateway_type)
    purchase_type: PurchaseType = dialog_manager.dialog_data["purchase_type"]

    if not duration or not payment_gateway:
        logger.error(f"{user.log} Failed to find duration or gateway for payment creation")
        return None

    transaction_plan = PlanSnapshotDto.from_plan(plan, duration.days)
    price = duration.get_price(payment_gateway.currency)
    pricing = pricing_service.calculate(
        user,
        price,
        payment_gateway.currency,
        extra_discount_percent=_get_promocode_discount(dialog_manager),
    )

    try:
        result = await create_payment(
            user,
            CreatePaymentDto(
                plan_snapshot=transaction_plan,
                pricing=pricing,
                purchase_type=purchase_type,
                gateway_type=gateway_type,
                promocode_id=dialog_manager.dialog_data.get(CURRENT_PROMOCODE_ID_KEY),
                platega_payment_method=platega_payment_method,
            ),
        )

        return CachedPaymentData(
            payment_id=str(result.id),
            payment_url=result.url,
            final_pricing=retort.dump(pricing),
        )

    except Exception:
        logger.error(f"{user.log} Failed to create paymen")
        await notifier.notify_user(user, i18n_key="ntf-subscription.payment-creation-failed")
        raise


async def _get_plans_for_purchase(
    user: UserDto,
    purchase_type: PurchaseType,
    get_available_plans: GetAvailablePlans,
    plan_dao: PlanDao,
    subscription_dao: SubscriptionDao,
) -> list[PlanDto]:
    if purchase_type == PurchaseType.TRAFFIC_TOPUP:
        if not await subscription_dao.get_current(user.telegram_id):
            return []
        plans = await plan_dao.filter_by_availability(PlanAvailability.TRAFFIC_TOPUP)
        return [plan for plan in plans if plan.is_active and not plan.is_trial]

    if purchase_type == PurchaseType.DEVICE_TOPUP:
        if not await subscription_dao.get_current(user.telegram_id):
            return []
        plans = await plan_dao.filter_by_availability(PlanAvailability.DEVICE_TOPUP)
        return [plan for plan in plans if plan.is_active and not plan.is_trial]

    return await get_available_plans.system(user)


async def _open_purchase_flow(
    purchase_type: PurchaseType,
    dialog_manager: DialogManager,
    retort: Retort,
    payment_gateway_dao: PaymentGatewayDao,
    pricing_service: PricingService,
    notifier: Notifier,
    get_available_plans: GetAvailablePlans,
    create_payment: CreatePayment,
    plan_dao: PlanDao,
    subscription_dao: SubscriptionDao,
    force_start: bool = False,
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    plans = await _get_plans_for_purchase(
        user=user,
        purchase_type=purchase_type,
        get_available_plans=get_available_plans,
        plan_dao=plan_dao,
        subscription_dao=subscription_dao,
    )
    gateways = await payment_gateway_dao.get_active()

    dialog_manager.dialog_data["purchase_type"] = purchase_type
    dialog_manager.dialog_data["available_plans"] = [retort.dump(plan) for plan in plans]
    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_METHOD_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_METHOD_OPTION_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_PLATEGA_METHOD_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_PROMOCODE_ID_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_PROMOCODE_DISCOUNT_KEY, None)
    dialog_manager.dialog_data.pop(PAYMENT_CACHE_KEY, None)

    if not plans:
        logger.warning(f"{user.log} No available plans for purchase type '{purchase_type}'")
        await notifier.notify_user(user, i18n_key="ntf-subscription.plans-unavailable")
        return

    if not gateways:
        logger.warning(f"{user.log} No active payment gateways")
        await notifier.notify_user(user, i18n_key="ntf-subscription.gateways-unavailable")
        return

    payment_options = _get_payment_options(gateways)
    if not payment_options:
        logger.warning(f"{user.log} No usable payment options")
        await notifier.notify_user(user, i18n_key="ntf-subscription.gateways-unavailable")
        return

    if len(plans) == 1:
        logger.info(f"{user.log} Auto-selected single plan '{plans[0].id}'")
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plans[0])
        dialog_manager.dialog_data["only_single_plan"] = True

        if len(plans[0].durations) == 1:
            logger.info(f"{user.log} Auto-selected duration '{plans[0].durations[0].days}'")
            dialog_manager.dialog_data["selected_duration"] = plans[0].durations[0].days
            dialog_manager.dialog_data["only_single_duration"] = True

            if len(payment_options) == 1:
                payment_option = payment_options[0]
                selected_payment_method, platega_payment_method = _parse_payment_option(payment_option)
                logger.info(f"{user.log} Auto-selected payment method '{payment_option}'")
                dialog_manager.dialog_data[CURRENT_METHOD_KEY] = selected_payment_method
                dialog_manager.dialog_data[CURRENT_METHOD_OPTION_KEY] = payment_option
                dialog_manager.dialog_data[CURRENT_PLATEGA_METHOD_KEY] = platega_payment_method

                payment_data = await _create_payment_and_get_data(
                    dialog_manager=dialog_manager,
                    plan=plans[0],
                    duration_days=plans[0].durations[0].days,
                    gateway_type=selected_payment_method,
                    retort=retort,
                    payment_gateway_dao=payment_gateway_dao,
                    notifier=notifier,
                    pricing_service=pricing_service,
                    create_payment=create_payment,
                    platega_payment_method=platega_payment_method,
                )

                if payment_data:
                    _save_payment_data(dialog_manager, payment_data)

                target_state = Subscription.CONFIRM
                if force_start:
                    await dialog_manager.start(
                        state=target_state,
                        data=dict(dialog_manager.dialog_data),
                        mode=StartMode.RESET_STACK,
                    )
                else:
                    await dialog_manager.switch_to(state=target_state)
                return

            target_state = Subscription.PAYMENT_METHOD
            if force_start:
                await dialog_manager.start(
                    state=target_state,
                    data=dict(dialog_manager.dialog_data),
                    mode=StartMode.RESET_STACK,
                )
            else:
                await dialog_manager.switch_to(state=target_state)
            return

        target_state = Subscription.DURATION
        if force_start:
            await dialog_manager.start(
                state=target_state,
                data=dict(dialog_manager.dialog_data),
                mode=StartMode.RESET_STACK,
            )
        else:
            await dialog_manager.switch_to(state=target_state)
        return

    dialog_manager.dialog_data["only_single_plan"] = False
    dialog_manager.dialog_data["only_single_duration"] = False
    target_state = Subscription.PLANS
    if force_start:
        await dialog_manager.start(
            state=target_state,
            data=dict(dialog_manager.dialog_data),
            mode=StartMode.RESET_STACK,
        )
    else:
        await dialog_manager.switch_to(state=target_state)


@inject
async def on_purchase_type_select(
    purchase_type: PurchaseType,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    notifier: FromDishka[Notifier],
    get_available_plans: FromDishka[GetAvailablePlans],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    plans: list[PlanDto] = await get_available_plans.system(user)
    gateways = await payment_gateway_dao.get_active()
    dialog_manager.dialog_data["purchase_type"] = purchase_type
    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)

    if not plans:
        logger.warning(f"{user.log} No available subscription plans")
        await notifier.notify_user(user, i18n_key="ntf-subscription.plans-unavailable")
        return

    if not gateways:
        logger.warning(f"{user.log} No active payment gateways")
        await notifier.notify_user(user, i18n_key="ntf-subscription.gateways-unavailable")
        return

    if len(plans) == 1:
        logger.info(f"{user.log} Auto-selected single plan '{plans[0].id}'")
        dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plans[0])
        dialog_manager.dialog_data["only_single_plan"] = True
        await dialog_manager.switch_to(state=Subscription.DURATION)
        return

    dialog_manager.dialog_data["only_single_plan"] = False
    await dialog_manager.switch_to(state=Subscription.PLANS)


@inject
async def on_subscription_plans(  # noqa: C901
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    notifier: FromDishka[Notifier],
    get_available_plans: FromDishka[GetAvailablePlans],
    create_payment: FromDishka[CreatePayment],
    plan_dao: FromDishka[PlanDao],
    subscription_dao: FromDishka[SubscriptionDao],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} Opened subscription plans menu")

    if not callback.data:
        raise ValueError("Callback data is empty")

    purchase_type = PurchaseType(callback.data.removeprefix(PAYMENT_PREFIX))
    await _open_purchase_flow(
        purchase_type=purchase_type,
        dialog_manager=dialog_manager,
        retort=retort,
        payment_gateway_dao=payment_gateway_dao,
        pricing_service=pricing_service,
        notifier=notifier,
        get_available_plans=get_available_plans,
        create_payment=create_payment,
        plan_dao=plan_dao,
        subscription_dao=subscription_dao,
    )


@inject
async def on_plan_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_plan: int,
    retort: FromDishka[Retort],
    plan_dao: FromDishka[PlanDao],
) -> None:
    _hydrate_dialog_data_from_start_data(dialog_manager)
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    plan = None
    for raw_plan in dialog_manager.dialog_data.get("available_plans", []):
        current_plan = retort.load(raw_plan, PlanDto)
        if current_plan.id == selected_plan:
            plan = current_plan
            break

    if plan is None:
        plan = await plan_dao.get_by_id(plan_id=selected_plan)

    if not plan:
        logger.error(f"{user.log} Selected plan with id '{selected_plan}', but it was not found")
        await dialog_manager.start(state=Subscription.MAIN)
        return

    logger.info(f"{user.log} Selected plan '{plan.id}'")

    dialog_manager.dialog_data[PlanDto.__name__] = retort.dump(plan)
    dialog_manager.dialog_data.pop(PAYMENT_CACHE_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_DURATION_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_METHOD_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_METHOD_OPTION_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_PLATEGA_METHOD_KEY, None)

    if len(plan.durations) == 1:
        logger.info(f"{user.log} Auto-selected single duration '{plan.durations[0].days}'")
        dialog_manager.dialog_data["only_single_duration"] = True
        await on_duration_select(callback, widget, dialog_manager, plan.durations[0].days)  # type:ignore[no-untyped-call]
        return

    dialog_manager.dialog_data["only_single_duration"] = False
    await dialog_manager.switch_to(state=Subscription.DURATION)


@inject
async def on_duration_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_duration: int,
    retort: FromDishka[Retort],
    settings_dao: FromDishka[SettingsDao],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    notifier: FromDishka[Notifier],
    pricing_service: FromDishka[PricingService],
    create_payment: FromDishka[CreatePayment],
) -> None:
    _hydrate_dialog_data_from_start_data(dialog_manager)
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    logger.info(f"{user.log} Selected subscription duration '{selected_duration}' days")
    dialog_manager.dialog_data[CURRENT_DURATION_KEY] = selected_duration

    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        logger.error("PlanDto not found in dialog data")
        await dialog_manager.start(state=Subscription.MAIN)

    plan = retort.load(raw_plan, PlanDto)
    settings = await settings_dao.get()
    gateways = await payment_gateway_dao.get_active()
    payment_options = _get_payment_options(gateways)
    currency = settings.default_currency
    price = pricing_service.calculate(
        user,
        price=plan.get_duration(selected_duration).get_price(currency),  # type: ignore[union-attr]
        currency=currency,
        extra_discount_percent=_get_promocode_discount(dialog_manager),
    )
    dialog_manager.dialog_data["is_free"] = price.is_free

    if not gateways:
        await notifier.notify_user(user, i18n_key="ntf-subscription.gateways-unavailable")
        return
    if not payment_options:
        await notifier.notify_user(user, i18n_key="ntf-subscription.gateways-unavailable")
        return

    if len(payment_options) == 1 or price.is_free:
        payment_option = payment_options[0]
        selected_payment_method, platega_payment_method = _parse_payment_option(payment_option)
        dialog_manager.dialog_data[CURRENT_METHOD_KEY] = selected_payment_method
        dialog_manager.dialog_data[CURRENT_METHOD_OPTION_KEY] = payment_option
        dialog_manager.dialog_data[CURRENT_PLATEGA_METHOD_KEY] = platega_payment_method

        cache = _load_payment_data(dialog_manager)
        cache_key = _get_cache_key(selected_duration, payment_option)

        if cache_key in cache:
            logger.info(f"{user.log} Re-selected same duration and single gateway")
            _save_payment_data(dialog_manager, cache[cache_key])
            await dialog_manager.switch_to(state=Subscription.CONFIRM)
            return

        logger.info(f"{user.log} Auto-selected single gateway '{selected_payment_method}'")

        payment_data = await _create_payment_and_get_data(
            dialog_manager=dialog_manager,
            plan=plan,
            duration_days=selected_duration,
            gateway_type=selected_payment_method,
            retort=retort,
            payment_gateway_dao=payment_gateway_dao,
            notifier=notifier,
            pricing_service=pricing_service,
            create_payment=create_payment,
            platega_payment_method=platega_payment_method,
        )

        if payment_data:
            cache[cache_key] = payment_data
            _save_payment_data(dialog_manager, payment_data)
            await dialog_manager.switch_to(state=Subscription.CONFIRM)
            return

    dialog_manager.dialog_data.pop(CURRENT_METHOD_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_METHOD_OPTION_KEY, None)
    dialog_manager.dialog_data.pop(CURRENT_PLATEGA_METHOD_KEY, None)
    await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)


@inject
async def on_payment_method_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_payment_method: str,
    retort: FromDishka[Retort],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    notifier: FromDishka[Notifier],
    pricing_service: FromDishka[PricingService],
    create_payment: FromDishka[CreatePayment],
) -> None:
    _hydrate_dialog_data_from_start_data(dialog_manager)
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    gateway_type, platega_payment_method = _parse_payment_option(selected_payment_method)
    logger.info(f"{user.log} Selected payment method '{selected_payment_method}'")

    selected_duration = dialog_manager.dialog_data[CURRENT_DURATION_KEY]
    dialog_manager.dialog_data[CURRENT_METHOD_KEY] = gateway_type
    dialog_manager.dialog_data[CURRENT_METHOD_OPTION_KEY] = selected_payment_method
    dialog_manager.dialog_data[CURRENT_PLATEGA_METHOD_KEY] = platega_payment_method
    cache = _load_payment_data(dialog_manager)
    cache_key = _get_cache_key(selected_duration, selected_payment_method)

    if cache_key in cache:
        logger.info(f"{user.log} Re-selected same method and duration")
        _save_payment_data(dialog_manager, cache[cache_key])
        await dialog_manager.switch_to(state=Subscription.CONFIRM)
        return

    logger.info(f"{user.log} New combination. Creating new payment")

    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        logger.error("PlanDto not found in dialog data")
        await dialog_manager.start(state=Subscription.MAIN)

    plan = retort.load(raw_plan, PlanDto)

    payment_data = await _create_payment_and_get_data(
        dialog_manager=dialog_manager,
        plan=plan,
        duration_days=selected_duration,
        gateway_type=gateway_type,
        retort=retort,
        payment_gateway_dao=payment_gateway_dao,
        notifier=notifier,
        pricing_service=pricing_service,
        create_payment=create_payment,
        platega_payment_method=platega_payment_method,
    )

    if payment_data:
        cache[cache_key] = payment_data
        _save_payment_data(dialog_manager, payment_data)

    await dialog_manager.switch_to(state=Subscription.CONFIRM)


@inject
async def on_device_topup(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await _notify_topup_support(
        callback,
        "Чтобы докупить устройства, обратитесь в поддержку:",
    )


async def on_traffic_topup(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
) -> None:
    await _notify_topup_support(
        callback,
        "Чтобы докупить трафик, обратитесь в поддержку:",
    )


@inject
async def on_get_subscription(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    process_payment: FromDishka[ProcessPayment],
) -> None:
    user: UserDto = dialog_manager.middleware_data[USER_KEY]
    payment_id = dialog_manager.dialog_data["payment_id"]
    logger.info(f"{user.log} Getted free subscription '{payment_id}'")
    await process_payment.system(ProcessPaymentDto(payment_id, TransactionStatus.COMPLETED))


@inject
async def on_promocode_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    promocode_dao: FromDishka[PromocodeDao],
    notifier: FromDishka[Notifier],
) -> None:
    _hydrate_dialog_data_from_start_data(dialog_manager)
    user: UserDto = dialog_manager.middleware_data[USER_KEY]

    if not message.text:
        await notifier.notify_user(user, i18n_key="ntf-promocode.invalid")
        return

    promocode = await promocode_dao.get_by_code(message.text.strip().upper())
    if not promocode or not promocode.is_active:
        await notifier.notify_user(user, i18n_key="ntf-promocode.invalid")
        return

    if promocode.expires_at and promocode.expires_at <= datetime_now():
        await notifier.notify_user(user, i18n_key="ntf-promocode.expired")
        return

    if promocode.max_activations is not None:
        activations = await promocode_dao.count_activations(promocode.id)  # type: ignore[arg-type]
        if activations >= promocode.max_activations:
            await notifier.notify_user(user, i18n_key="ntf-promocode.limit-reached")
            return

    already_used = await promocode_dao.has_user_activation(
        promocode.id,  # type: ignore[arg-type]
        user.telegram_id,
    )
    if already_used:
        await notifier.notify_user(user, i18n_key="ntf-promocode.already-used")
        return

    dialog_manager.dialog_data[CURRENT_PROMOCODE_ID_KEY] = promocode.id
    dialog_manager.dialog_data[CURRENT_PROMOCODE_DISCOUNT_KEY] = promocode.discount_percent
    dialog_manager.dialog_data.pop(PAYMENT_CACHE_KEY, None)

    await notifier.notify_user(
        user,
        payload=MessagePayloadDto(
            i18n_key="ntf-promocode.applied",
            i18n_kwargs={
                "code": promocode.code,
                "discount_percent": promocode.discount_percent,
            },
        ),
    )
    await dialog_manager.switch_to(state=Subscription.PAYMENT_METHOD)
