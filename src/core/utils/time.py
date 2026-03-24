import time
from datetime import datetime, timedelta

from remnapy.enums.users import TrafficLimitStrategy

from src.core.constants import TIMEZONE

START_TIME: int = int(time.time())


def datetime_now() -> datetime:
    return datetime.now(tz=TIMEZONE)


def get_uptime() -> int:
    uptime_seconds = int(time.time() - START_TIME)
    return uptime_seconds


def get_traffic_reset_delta(strategy: TrafficLimitStrategy) -> timedelta:
    now = datetime_now()

    if strategy == TrafficLimitStrategy.NO_RESET:
        return timedelta(seconds=0)

    if strategy == TrafficLimitStrategy.DAY:
        next_day = now.date() + timedelta(days=1)
        reset_at = datetime.combine(next_day, datetime.min.time(), tzinfo=TIMEZONE)
        return reset_at - now

    if strategy == TrafficLimitStrategy.WEEK:
        weekday = now.weekday()
        days_until = (7 - weekday) % 7 or 7
        date_target = now.date() + timedelta(days=days_until)
        reset_at = datetime(
            date_target.year, date_target.month, date_target.day, 0, 5, 0, tzinfo=TIMEZONE
        )
        return reset_at - now

    if strategy == TrafficLimitStrategy.MONTH:
        year = now.year
        month = now.month + 1
        if month == 13:
            year += 1
            month = 1
        reset_at = datetime(year, month, 1, 0, 10, 0, tzinfo=TIMEZONE)
        return reset_at - now

    raise ValueError("Unsupported strategy")
