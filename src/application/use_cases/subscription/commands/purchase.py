from decimal import Decimal
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from loguru import logger

from src.application.common import EventPublisher, Interactor, Redirect, Remnawave, TranslatorRunner
from src.application.common.dao import ReferralDao, SettingsDao, SubscriptionDao, TransactionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanSnapshotDto, ReferralRewardDto, SubscriptionDto, TransactionDto, UserDto
from src.application.events import (
    ReferralRewardFailedEvent,
    ReferralRewardReceivedEvent,
    TrialActivatedEvent,
)
from src.application.use_cases.subscription.commands.management import (
    AddSubscriptionDuration,
    AddSubscriptionDurationDto,
)
from src.application.use_cases.user.commands.profile_edit import (
    ChangeUserPoints,
    ChangeUserPointsDto,
)
from src.core.enums import (
    PurchaseType,
    ReferralAccrualStrategy,
    ReferralLevel,
    ReferralRewardStrategy,
    ReferralRewardType,
    SubscriptionStatus,
    TransactionStatus,
)
from src.core.exceptions import PurchaseError, TrialError
from src.core.types import RemnaUserDto
from src.core.utils.converters import days_to_datetime
from src.core.utils.i18n_helpers import (
    i18n_format_days,
    i18n_format_device_limit,
    i18n_format_traffic_limit,
)
from src.core.utils.time import datetime_now


@dataclass(frozen=True)
class ActivateTrialSubscriptionDto:
    user: UserDto
    plan: PlanSnapshotDto


class ActivateTrialSubscription(Interactor[ActivateTrialSubscriptionDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        settings_dao: SettingsDao,
        referral_dao: ReferralDao,
        subscription_dao: SubscriptionDao,
        remnawave: Remnawave,
        event_publisher: EventPublisher,
        redirect: Redirect,
        i18n: TranslatorRunner,
        change_user_points: ChangeUserPoints,
        add_subscription_duration: AddSubscriptionDuration,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.settings_dao = settings_dao
        self.referral_dao = referral_dao
        self.subscription_dao = subscription_dao
        self.remnawave = remnawave
        self.event_publisher = event_publisher
        self.redirect = redirect
        self.i18n = i18n
        self.change_user_points = change_user_points
        self.add_subscription_duration = add_subscription_duration

    async def _execute(self, actor: UserDto, data: ActivateTrialSubscriptionDto) -> None:
        user = data.user
        plan = data.plan

        logger.info(f"{actor.log} Started trial for user '{user.telegram_id}'")

        try:
            created_user = await self.remnawave.create_user(user, plan=plan)

            trial_subscription = SubscriptionDto(
                user_remna_id=created_user.uuid,
                status=SubscriptionStatus(created_user.status),
                is_trial=True,
                traffic_limit=plan.traffic_limit,
                device_limit=plan.device_limit,
                traffic_limit_strategy=plan.traffic_limit_strategy,
                tag=plan.tag,
                internal_squads=plan.internal_squads,
                external_squad=plan.external_squad,
                expire_at=created_user.expire_at,
                url=created_user.subscription_url,
                plan_snapshot=plan,
            )

            async with self.uow:
                await self.subscription_dao.create(
                    subscription=trial_subscription,
                    telegram_id=user.telegram_id,
                )
                await self.user_dao.set_trial_available(user.telegram_id, False)
                await self.uow.commit()

            logger.debug(
                f"{actor.log} Created new trial subscription for user '{user.telegram_id}'"
            )

            event = TrialActivatedEvent(
                telegram_id=user.telegram_id,
                username=user.username,
                name=user.name,
                plan_name=self.i18n.get(plan.name),
                plan_type=plan.type,
                plan_traffic_limit=i18n_format_traffic_limit(plan.traffic_limit),
                plan_device_limit=i18n_format_device_limit(plan.device_limit),
                plan_duration=i18n_format_days(plan.duration),
            )
            await self.event_publisher.publish(event)
            await self._assign_trial_referral_rewards(user, plan)
            await self.redirect.to_success_trial(user.telegram_id)
            logger.info(
                f"{actor.log} Trial subscription completed "
                f"successfully for user '{user.telegram_id}'"
            )

        except Exception as e:
            logger.exception(f"{actor.log} Failed to give trial for user '{user.telegram_id}'")
            await self.redirect.to_failed_payment(user.telegram_id)
            raise TrialError(e)

    async def _assign_trial_referral_rewards(
        self,
        user: UserDto,
        plan: PlanSnapshotDto,
    ) -> None:
        settings = await self.settings_dao.get()

        if not settings.referral.enable:
            return

        if settings.referral.accrual_strategy != ReferralAccrualStrategy.ON_TRIAL_ACTIVATION:
            return

        referral, parent = await self.referral_dao.get_referral_chain(user.telegram_id)
        if not referral:
            return

        reward_chain = {ReferralLevel.FIRST: referral.referrer}
        if parent:
            reward_chain[ReferralLevel.SECOND] = parent.referrer

        for level, referrer in reward_chain.items():
            if level > settings.referral.level:
                continue

            config_value = settings.referral.reward.config.get(level)
            if config_value is None:
                continue

            reward_amount = self._calculate_trial_reward_amount(
                duration=plan.duration,
                config_value=config_value,
                reward_strategy=settings.referral.reward.strategy,
            )
            if reward_amount <= 0:
                continue

            async with self.uow:
                reward = await self.referral_dao.create_reward(
                    reward=ReferralRewardDto(
                        user_telegram_id=referrer.telegram_id,
                        type=settings.referral.reward.type,
                        amount=reward_amount,
                        is_issued=False,
                    ),
                    referral_id=referral.id,  # type: ignore[arg-type]
                )
                await self.uow.commit()

            await self._apply_referral_reward(
                reward=reward,
                referred_name=user.name,
                reward_type=settings.referral.reward.type,
            )

    def _calculate_trial_reward_amount(
        self,
        duration: int,
        config_value: int,
        reward_strategy: ReferralRewardStrategy,
    ) -> int:
        if reward_strategy == ReferralRewardStrategy.AMOUNT:
            return config_value

        percentage = Decimal(config_value) / Decimal(100)
        return max(1, int(Decimal(duration) * percentage))

    async def _apply_referral_reward(
        self,
        reward: ReferralRewardDto,
        referred_name: str,
        reward_type: ReferralRewardType,
    ) -> None:
        referrer = await self.user_dao.get_by_telegram_id(reward.user_telegram_id)
        if not referrer:
            return

        if reward_type == ReferralRewardType.POINTS:
            await self.change_user_points.system(
                ChangeUserPointsDto(
                    telegram_id=referrer.telegram_id,
                    amount=reward.amount,
                )
            )
        else:
            subscription = await self.subscription_dao.get_current(referrer.telegram_id)
            if not subscription or subscription.is_trial:
                await self.event_publisher.publish(
                    ReferralRewardFailedEvent(
                        user=referrer,
                        name=referred_name,
                        value=reward.amount,
                        reward_type=reward_type,
                    )
                )
                return

            await self.add_subscription_duration.system(
                AddSubscriptionDurationDto(
                    telegram_id=referrer.telegram_id,
                    days=reward.amount,
                )
            )

        await self.event_publisher.publish(
            ReferralRewardReceivedEvent(
                user=referrer,
                name=referred_name,
                value=reward.amount,
                reward_type=reward_type,
            )
        )
        await self.referral_dao.mark_reward_as_issued(reward.id)  # type: ignore[arg-type]


@dataclass(frozen=True)
class PurchaseSubscriptionDto:
    user: UserDto
    transaction: TransactionDto
    subscription: Optional[SubscriptionDto]


class PurchaseSubscription(Interactor[PurchaseSubscriptionDto, None]):
    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        transaction_dao: TransactionDao,
        remnawave: Remnawave,
        redirect: Redirect,
    ) -> None:
        self.uow = uow
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.transaction_dao = transaction_dao
        self.remnawave = remnawave
        self.redirect = redirect

    async def _execute(self, actor: UserDto, data: PurchaseSubscriptionDto) -> None:
        user = data.user
        transaction = data.transaction
        subscription = data.subscription
        plan = transaction.plan_snapshot
        purchase_type = transaction.purchase_type
        has_trial = subscription.is_trial if subscription else False

        if not user or not plan:
            logger.error(f"{actor.log} User or plan not found for transaction '{transaction.id}'")
            return

        logger.info(
            f"{actor.log} Purchase subscription started: '{purchase_type}' "
            f"for user '{user.telegram_id}'"
        )

        async with self.uow:
            try:
                # 1. NEW PURCHASE (NOT TRIAL)
                if purchase_type == PurchaseType.NEW and not has_trial:
                    created_user = await self.remnawave.create_user(user, plan=plan)
                    new_sub = self._build_subscription_dto(created_user, plan)

                    await self.subscription_dao.create(
                        subscription=new_sub,
                        telegram_id=user.telegram_id,
                    )
                    await self.user_dao.set_trial_available(user.telegram_id, False)
                    await self.uow.commit()

                    logger.debug(
                        f"{actor.log} Created new subscription for user '{user.telegram_id}'"
                    )

                # 2. RENEW (NOT TRIAL)
                elif purchase_type == PurchaseType.RENEW and not has_trial:
                    if not subscription:
                        raise ValueError(
                            f"No subscription found for renewal for user '{user.telegram_id}'"
                        )

                    base_date = max(subscription.expire_at, datetime_now())
                    duration = transaction.plan_snapshot.duration

                    if duration == 0:
                        new_expire = days_to_datetime(duration)  # unlimited
                    else:
                        base_date = max(subscription.expire_at, datetime_now())
                        new_expire = base_date + timedelta(days=duration)

                    subscription.expire_at = new_expire

                    updated_user = await self.remnawave.update_user(
                        user=user,
                        uuid=subscription.user_remna_id,
                        subscription=subscription,
                        reset_traffic=True,
                    )

                    subscription.plan_snapshot = plan
                    await self.subscription_dao.update(subscription)
                    await self.uow.commit()
                    logger.debug(f"{actor.log} Renewed subscription for user '{user.telegram_id}'")

                # 3. CHANGE OR CONVERT FROM TRIAL
                elif purchase_type == PurchaseType.CHANGE or has_trial:
                    if not subscription:
                        raise ValueError(
                            f"No subscription found for change for user '{user.telegram_id}'"
                        )

                    # Deactivate old subscription
                    await self.subscription_dao.update_status(
                        subscription_id=subscription.id,  # type: ignore[arg-type]
                        status=SubscriptionStatus.DELETED,
                    )

                    updated_user = await self.remnawave.update_user(
                        user=user,
                        uuid=subscription.user_remna_id,
                        plan=plan,
                        reset_traffic=True,
                    )

                    new_sub = self._build_subscription_dto(updated_user, plan)
                    await self.subscription_dao.create(
                        subscription=new_sub,
                        telegram_id=user.telegram_id,
                    )

                    await self.uow.commit()
                    logger.debug(f"{actor.log} Changed subscription for user '{user.telegram_id}'")

                else:
                    raise ValueError(
                        f"Unknown purchase type '{purchase_type}' for user '{user.telegram_id}'"
                    )

                await self.redirect.to_success_payment(user.telegram_id, purchase_type)
                logger.info(
                    f"{actor.log} Purchase subscription completed for user '{user.telegram_id}'"
                )

            except Exception as e:
                logger.exception(
                    f"{actor.log} Failed to process purchase type '{purchase_type}' "
                    f"for user '{user.telegram_id}'"
                )

                await self.transaction_dao.update_status(
                    transaction.payment_id,
                    TransactionStatus.FAILED,
                )
                await self.uow.commit()

                await self.redirect.to_failed_payment(user.telegram_id)
                raise PurchaseError(e)

    def _build_subscription_dto(
        self,
        remna_user: RemnaUserDto,
        plan: PlanSnapshotDto,
    ) -> SubscriptionDto:
        return SubscriptionDto(
            user_remna_id=remna_user.uuid,
            status=SubscriptionStatus(remna_user.status),
            traffic_limit=plan.traffic_limit,
            device_limit=plan.device_limit,
            traffic_limit_strategy=plan.traffic_limit_strategy,
            tag=plan.tag,
            internal_squads=plan.internal_squads,
            external_squad=plan.external_squad,
            expire_at=remna_user.expire_at,
            url=remna_user.subscription_url,
            plan_snapshot=plan,
        )
