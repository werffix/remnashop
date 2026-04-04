from typing import Any, cast

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import TranslatorRunner
from src.application.common.dao import PaymentGatewayDao, PlanDao, SettingsDao, SubscriptionDao
from src.application.dto import PlanDto, PriceDetailsDto, UserDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.application.services import PricingService
from src.application.use_cases.plan.queries.match import MatchPlan, MatchPlanDto
from src.application.use_cases.user.queries.plans import GetAvailablePlans
from src.core.config import AppConfig
from src.core.enums import PaymentGatewayType, PurchaseType
from src.core.utils.i18n_helpers import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_expire_time,
    i18n_format_traffic_limit,
)
from src.telegram.states import Subscription


def _get_promocode_discount(dialog_manager: DialogManager) -> int:
    return int(dialog_manager.dialog_data.get("selected_promocode_discount", 0) or 0)


def _hydrate_dialog_data_from_start_data(dialog_manager: DialogManager) -> None:
    start_data = dialog_manager.start_data
    if not isinstance(start_data, dict):
        return

    for key, value in start_data.items():
        dialog_manager.dialog_data.setdefault(key, value)


def _get_platega_method_label(method: int) -> str:
    mapping = {
        2: "СБП",
        11: "Карта",
        13: "Криптовалюта",
    }
    return mapping.get(method, str(method))


def _count_payment_options(gateways: list[Any]) -> int:
    count = 0
    for gateway in gateways:
        if gateway.type == PaymentGatewayType.PLATEGA and isinstance(
            gateway.settings, PlategaGatewaySettingsDto
        ):
            methods = gateway.settings.payment_methods
            count += len(methods)
            continue
        count += 1
    return count


@inject
async def subscription_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    subscription_dao: FromDishka[SubscriptionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.telegram_id)
    has_active = bool(current_subscription and not current_subscription.is_trial)
    is_unlimited = current_subscription.is_unlimited if current_subscription else False
    return {
        "has_active_subscription": has_active,
        "is_not_unlimited": not is_unlimited,
    }


@inject
async def plan_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    i18n: FromDishka[TranslatorRunner],
    plan_dao: FromDishka[PlanDao],
    subscription_dao: FromDishka[SubscriptionDao],
    match_plan: FromDishka[MatchPlan],
    **kwargs: Any,
) -> dict[str, Any]:
    plan_id: int = dialog_manager.start_data["plan_id"]  # type: ignore[call-overload, index, assignment]
    plan = await plan_dao.get_by_id(plan_id)

    if not plan:
        raise ValueError(f"Plan with id '{plan_id}' not found")

    current_subscription = await subscription_dao.get_current(user.telegram_id)

    if current_subscription:
        matched_plan = await match_plan.system(
            MatchPlanDto(plan_snapshot=current_subscription.plan_snapshot, plans=[plan])
        )

        if matched_plan and not current_subscription.is_unlimited:
            purchase_type = PurchaseType.RENEW
        else:
            purchase_type = PurchaseType.CHANGE
    else:
        purchase_type = PurchaseType.NEW

    dialog_manager.dialog_data["only_single_plan"] = True
    dialog_manager.dialog_data["purchase_type"] = purchase_type

    return {
        "plan_id": [plan.id],
        "name": i18n.get(plan.name),
        "description": i18n.get(plan.description) if plan.description else False,
        "purchase_type": purchase_type,
    }


@inject
async def plans_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    get_available_plans: FromDishka[GetAvailablePlans],
    **kwargs: Any,
) -> dict[str, Any]:
    _hydrate_dialog_data_from_start_data(dialog_manager)
    raw_plans = dialog_manager.dialog_data.get("available_plans")
    plans = [retort.load(raw_plan, PlanDto) for raw_plan in raw_plans] if raw_plans else await get_available_plans.system(user)

    formatted_plans = [{"id": plan.id, "name": i18n.get(plan.name)} for plan in plans]

    return {
        "plans": formatted_plans,
    }


@inject
async def duration_getter(
    dialog_manager: DialogManager,
    user: UserDto,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    settings_dao: FromDishka[SettingsDao],
    pricing_service: FromDishka[PricingService],
    **kwargs: Any,
) -> dict[str, Any]:
    _hydrate_dialog_data_from_start_data(dialog_manager)
    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        logger.debug("PlanDto not found in dialog data")
        await dialog_manager.start(state=Subscription.MAIN)

    plan = retort.load(raw_plan, PlanDto)
    settings = await settings_dao.get()
    currency = settings.default_currency
    only_single_plan = dialog_manager.dialog_data.get("only_single_plan", False)
    dialog_manager.dialog_data["is_free"] = False
    durations = []

    for duration in plan.durations:
        key, kw = i18n_format_days(duration.days)
        price = pricing_service.calculate(
            user,
            duration.get_price(currency),
            currency,
            extra_discount_percent=_get_promocode_discount(dialog_manager),
        )
        durations.append(
            {
                "days": duration.days,
                "period": i18n.get(key, **kw),
                "final_amount": price.final_amount,
                "discount_percent": price.discount_percent,
                "original_amount": price.original_amount,
                "currency": currency.symbol,
            }
        )

    return {
        "plan": i18n.get(plan.name),
        "description": i18n.get(plan.description) if plan.description else False,
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "durations": durations,
        "period": 0,
        "final_amount": 0,
        "currency": "",
        "only_single_plan": only_single_plan,
    }


@inject
async def payment_method_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    pricing_service: FromDishka[PricingService],
    user: UserDto,
    **kwargs: Any,
) -> dict[str, Any]:
    _hydrate_dialog_data_from_start_data(dialog_manager)
    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        logger.error("PlanDto not found in dialog data")
        await dialog_manager.start(state=Subscription.MAIN)

    plan = retort.load(raw_plan, PlanDto)
    gateways = await payment_gateway_dao.get_active()
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    only_single_duration = dialog_manager.dialog_data.get("only_single_duration", False)
    duration = plan.get_duration(selected_duration)

    if not duration:
        raise ValueError(f"Duration '{selected_duration}' not found in plan '{plan.name}'")

    payment_methods = []
    for gateway in gateways:
        pricing = pricing_service.calculate(
            user,
            duration.get_price(gateway.currency),
            gateway.currency,
            extra_discount_percent=_get_promocode_discount(dialog_manager),
        )
        if gateway.type == PaymentGatewayType.PLATEGA and isinstance(
            gateway.settings, PlategaGatewaySettingsDto
        ):
            methods = gateway.settings.payment_methods
            if not methods:
                continue
            for method in methods:
                payment_methods.append(
                    {
                        "id": f"{gateway.type.value}:{method}",
                        "gateway_type": gateway.type,
                        "label": _get_platega_method_label(method),
                        "price": pricing.final_amount,
                        "currency": gateway.currency.symbol,
                    }
                )
            continue

        payment_methods.append(
            {
                "id": gateway.type.value,
                "gateway_type": gateway.type,
                "label": i18n.get("gateway-type", gateway_type=gateway.type),
                "price": pricing.final_amount,
                "currency": gateway.currency.symbol,
            }
        )

    key, kw = i18n_format_days(duration.days)

    return {
        "plan": i18n.get(plan.name),
        "description": i18n.get(plan.description) if plan.description else False,
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "period": i18n.get(key, **kw),
        "payment_methods": payment_methods,
        "final_amount": 0,
        "currency": "",
        "only_single_duration": only_single_duration,
    }


@inject
async def confirm_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    i18n: FromDishka[TranslatorRunner],
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    _hydrate_dialog_data_from_start_data(dialog_manager)
    raw_plan = dialog_manager.dialog_data.get(PlanDto.__name__)

    if not raw_plan:
        logger.debug("PlanDto not found in dialog data")
        await dialog_manager.start(state=Subscription.MAIN)

    plan = retort.load(raw_plan, PlanDto)
    selected_duration = dialog_manager.dialog_data["selected_duration"]
    only_single_duration = dialog_manager.dialog_data.get("only_single_duration", False)
    is_free = dialog_manager.dialog_data.get("is_free", False)
    selected_payment_method = dialog_manager.dialog_data["selected_payment_method"]
    purchase_type = dialog_manager.dialog_data["purchase_type"]
    payment_gateway = await payment_gateway_dao.get_by_type(selected_payment_method)
    duration = plan.get_duration(selected_duration)

    if not duration:
        raise ValueError(f"Duration '{selected_duration}' not found in plan '{plan.name}'")

    if not payment_gateway:
        raise ValueError(f"Not found PaymentGateway by selected type '{selected_payment_method}'")

    result_url = dialog_manager.dialog_data["payment_url"]
    pricing_data = dialog_manager.dialog_data["final_pricing"]
    pricing = retort.load(pricing_data, PriceDetailsDto)

    key, kw = i18n_format_days(duration.days)
    gateways = await payment_gateway_dao.get_active()

    return {
        "purchase_type": purchase_type,
        "plan": i18n.get(plan.name),
        "description": i18n.get(plan.description) if plan.description else False,
        "type": plan.type,
        "devices": i18n_format_device_limit(plan.device_limit),
        "traffic": i18n_format_traffic_limit(plan.traffic_limit),
        "period": i18n.get(key, **kw),
        "payment_method": selected_payment_method,
        "final_amount": pricing.final_amount,
        "discount_percent": pricing.discount_percent,
        "original_amount": pricing.original_amount,
        "currency": payment_gateway.currency.symbol,
        "url": result_url,
        "only_single_gateway": _count_payment_options(gateways) == 1,
        "only_single_duration": only_single_duration,
        "is_free": is_free,
    }


@inject
async def getter_connect(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: UserDto,
    subscription_dao: FromDishka[SubscriptionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.telegram_id)

    if not current_subscription:
        raise ValueError(f"User '{user.telegram_id}' has no active subscription after purchase")

    return {
        "is_mini_app": config.bot.is_mini_app,
        "connection_url": config.bot.mini_app_url or current_subscription.url,
        "connectable": True,
    }


@inject
async def success_payment_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: UserDto,
    subscription_dao: FromDishka[SubscriptionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    start_data = cast(dict[str, Any], dialog_manager.start_data)
    purchase_type: PurchaseType = start_data["purchase_type"]
    subscription = await subscription_dao.get_current(user.telegram_id)

    if not subscription:
        raise ValueError(f"User '{user.telegram_id}' has no active subscription after purchase")

    return {
        "purchase_type": purchase_type,
        "plan_name": subscription.plan_snapshot.name,
        "traffic_limit": i18n_format_traffic_limit(subscription.traffic_limit),
        "device_limit": i18n_format_device_limit(subscription.device_limit),
        "expire_time": i18n_format_expire_time(subscription.expire_at),
        "added_duration": i18n_format_days(subscription.plan_snapshot.duration),
        "is_mini_app": config.bot.is_mini_app,
        "connection_url": config.bot.mini_app_url or subscription.url,
        "connectable": True,
    }
