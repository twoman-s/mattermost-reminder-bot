"""
Service for calculating recurrence dates and rules.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from reminders.models import Reminder, RepeatType


def weekday_to_int(weekday_name: str) -> int:
    """Map weekday name to integer (0=Monday, 6=Sunday)."""
    mapping = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    val = mapping.get(weekday_name.lower())
    if val is None:
        raise ValueError(f"Invalid weekday name: {weekday_name}")
    return val


def set_day_clipped(dt: datetime, target_day: int) -> datetime:
    """Set the day of a datetime, clipping to the maximum days in that month."""
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    day = min(target_day, last_day)
    return dt.replace(day=day)


def get_nth_weekday_of_month(year: int, month: int, week: str, weekday: str) -> int:
    """
    Get the day number (1-31) of the N-th occurrence of a weekday in a month.
    week options: first, second, third, fourth, last
    weekday options: monday, ..., sunday
    """
    weekday_num = weekday_to_int(weekday)
    _, num_days = calendar.monthrange(year, month)
    days = [d for d in range(1, num_days + 1) if calendar.weekday(year, month, d) == weekday_num]

    if week == "first":
        return days[0]
    elif week == "second":
        return days[1]
    elif week == "third":
        return days[2]
    elif week == "fourth":
        return days[3]
    elif week == "last":
        return days[-1]
    raise ValueError(f"Unknown week position: {week}")


class RecurrenceService:
    """
    Service to calculate the next occurrence of a reminder.
    """

    @staticmethod
    def calculate_next_occurrence(reminder: Reminder) -> datetime | None:
        """
        Calculate the next scheduled datetime for the reminder based on its settings.
        Returns None if the recurrence has ended.
        """
        if reminder.repeat_type == RepeatType.NONE:
            return None

        current_dt = reminder.reminder_datetime
        next_dt = current_dt

        if reminder.repeat_type == RepeatType.INTERVAL:
            interval = reminder.repeat_interval
            unit = reminder.repeat_unit
            if unit == "minute":
                next_dt = next_dt + timedelta(minutes=interval)
            elif unit == "hour":
                next_dt = next_dt + timedelta(hours=interval)
            elif unit == "day":
                next_dt = next_dt + timedelta(days=interval)
            elif unit == "week":
                next_dt = next_dt + timedelta(weeks=interval)
            elif unit == "month":
                next_dt = next_dt + relativedelta(months=interval)
            elif unit == "year":
                next_dt = next_dt + relativedelta(years=interval)
            else:
                raise ValueError(f"Invalid repeat_unit: {unit}")

        elif reminder.repeat_type == RepeatType.WEEKLY:
            target_days = [weekday_to_int(day) for day in reminder.repeat_weekdays]
            if not target_days:
                target_days = [next_dt.weekday()]

            current_day = next_dt.weekday()
            offsets = []
            for t in target_days:
                diff = t - current_day
                if diff <= 0:
                    diff += 7
                offsets.append((diff, t))

            offsets.sort()
            min_diff, target_weekday = offsets[0]

            delta_days = min_diff
            if target_weekday <= current_day:
                delta_days += (reminder.repeat_interval - 1) * 7

            next_dt = next_dt + timedelta(days=delta_days)

        elif reminder.repeat_type == RepeatType.MONTHLY:
            if reminder.monthly_mode == "day_of_month":
                base_dt = next_dt + relativedelta(months=reminder.repeat_interval)
                next_dt = set_day_clipped(base_dt, reminder.monthly_day)
            elif reminder.monthly_mode == "weekday_position":
                base_dt = next_dt + relativedelta(months=reminder.repeat_interval)
                day_num = get_nth_weekday_of_month(
                    base_dt.year,
                    base_dt.month,
                    reminder.monthly_week,
                    reminder.monthly_weekday,
                )
                next_dt = base_dt.replace(day=day_num)
            else:
                raise ValueError(f"Invalid monthly_mode: {reminder.monthly_mode}")

        elif reminder.repeat_type == RepeatType.YEARLY:
            base_dt = next_dt + relativedelta(years=reminder.repeat_interval)
            base_dt = base_dt.replace(month=reminder.yearly_month)
            next_dt = set_day_clipped(base_dt, reminder.yearly_day)

        else:
            raise ValueError(f"Invalid repeat_type: {reminder.repeat_type}")

        return next_dt
