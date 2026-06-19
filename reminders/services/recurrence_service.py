"""
Recurrence engine for calculating next occurrences.

Supports:
  - Interval-based: every N minutes/hours/days/weeks/months/years
  - Weekly: specific weekdays (Monday, Monday+Friday, weekdays, etc.)
  - Monthly: day-of-month OR weekday-position (first Monday, last Friday, etc.)
  - Yearly: specific date each year
  - End conditions: forever, end-on-date, end-after-N-occurrences
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from dateutil.relativedelta import relativedelta
from django.utils import timezone

if TYPE_CHECKING:
    from reminders.models import Reminder

logger = logging.getLogger(__name__)

# Map weekday name → Python weekday int (Monday=0 … Sunday=6)
WEEKDAY_MAP: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class RecurrenceService:
    """
    Stateless service for computing next occurrences.

    All methods are classmethods/staticmethods so the service can be
    used without instantiation.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def calculate_next_occurrence(cls, reminder: "Reminder") -> datetime | None:
        """
        Calculate the next occurrence for a reminder based on its recurrence
        configuration. Returns None if the recurrence has ended.

        The returned datetime is always timezone-aware and guaranteed to be
        in the future relative to now().
        """
        from reminders.models import RepeatType

        now = timezone.now()

        handler = {
            RepeatType.INTERVAL: cls._next_interval,
            RepeatType.WEEKLY: cls._next_weekly,
            RepeatType.MONTHLY: cls._next_monthly,
            RepeatType.YEARLY: cls._next_yearly,
        }.get(reminder.repeat_type)

        if handler is None:
            return None  # One-time reminder — no next occurrence

        next_dt = handler(reminder, now)

        if next_dt is None:
            return None

        # Enforce end conditions
        if not reminder.repeat_forever:
            if reminder.repeat_end_date and next_dt.date() > reminder.repeat_end_date:
                logger.info(
                    "Reminder %s recurrence ended (end_date=%s, next would be %s).",
                    reminder.external_id,
                    reminder.repeat_end_date,
                    next_dt.date(),
                )
                return None

            if reminder.repeat_end_after is not None:
                # occurrence_count will be incremented BEFORE this check
                if reminder.occurrence_count >= reminder.repeat_end_after:
                    logger.info(
                        "Reminder %s recurrence ended (after %d/%d occurrences).",
                        reminder.external_id,
                        reminder.occurrence_count,
                        reminder.repeat_end_after,
                    )
                    return None

        return next_dt

    # ------------------------------------------------------------------
    # Interval-based recurrence
    # ------------------------------------------------------------------

    @classmethod
    def _next_interval(cls, reminder: "Reminder", now: datetime) -> datetime:
        """
        Every N minutes / hours / days / weeks / months / years.
        """
        n = reminder.repeat_interval or 1
        unit = reminder.repeat_unit or "day"

        delta_map = {
            "minute": lambda: timedelta(minutes=n),
            "hour": lambda: timedelta(hours=n),
            "day": lambda: timedelta(days=n),
            "week": lambda: timedelta(weeks=n),
            "month": lambda: relativedelta(months=n),
            "year": lambda: relativedelta(years=n),
        }

        make_delta = delta_map.get(unit)
        if make_delta is None:
            raise ValueError(f"Unknown repeat_unit: {unit}")

        delta = make_delta()
        next_dt = reminder.reminder_datetime + delta

        # Skip past occurrences that are still in the past
        while next_dt <= now:
            next_dt += delta

        return next_dt

    # ------------------------------------------------------------------
    # Weekly recurrence
    # ------------------------------------------------------------------

    @classmethod
    def _next_weekly(cls, reminder: "Reminder", now: datetime) -> datetime:
        """
        Next occurrence on one of the selected weekdays.
        Handles single weekday, multiple weekdays, and every-weekday.
        """
        weekdays = reminder.repeat_weekdays or []
        if not weekdays:
            # Fallback: same day next week
            next_dt = reminder.reminder_datetime + timedelta(weeks=1)
            while next_dt <= now:
                next_dt += timedelta(weeks=1)
            return next_dt

        target_ints = sorted(WEEKDAY_MAP[d] for d in weekdays if d in WEEKDAY_MAP)
        if not target_ints:
            next_dt = reminder.reminder_datetime + timedelta(weeks=1)
            while next_dt <= now:
                next_dt += timedelta(weeks=1)
            return next_dt

        current_dt = reminder.reminder_datetime
        time_part = current_dt.timetz()

        # Start searching from the day after the current occurrence
        search_date = current_dt.date() + timedelta(days=1)

        # Search up to 8 days (guarantees we wrap around the week)
        for offset in range(1, 400):  # safety bound
            candidate_date = current_dt.date() + timedelta(days=offset)
            if candidate_date.weekday() in target_ints:
                candidate_dt = datetime.combine(candidate_date, time_part)
                if timezone.is_naive(candidate_dt):
                    candidate_dt = timezone.make_aware(candidate_dt, timezone.get_current_timezone())
                if candidate_dt > now:
                    return candidate_dt

        # Should never reach here
        return current_dt + timedelta(weeks=1)

    # ------------------------------------------------------------------
    # Monthly recurrence
    # ------------------------------------------------------------------

    @classmethod
    def _next_monthly(cls, reminder: "Reminder", now: datetime) -> datetime:
        """
        Monthly recurrence via day-of-month or weekday-position.
        """
        from reminders.models import MonthlyMode

        if reminder.monthly_mode == MonthlyMode.WEEKDAY_POSITION:
            return cls._next_monthly_weekday_position(reminder, now)
        else:
            return cls._next_monthly_day(reminder, now)

    @classmethod
    def _next_monthly_day(cls, reminder: "Reminder", now: datetime) -> datetime:
        """
        Nth day of every month. If the month doesn't have that day,
        use the last day of the month.
        """
        target_day = reminder.monthly_day or reminder.reminder_datetime.day
        n = reminder.repeat_interval or 1
        current_dt = reminder.reminder_datetime
        time_part = current_dt.timetz()

        candidate = current_dt + relativedelta(months=n)

        # Clamp to valid day
        max_day = calendar.monthrange(candidate.year, candidate.month)[1]
        actual_day = min(target_day, max_day)
        candidate = candidate.replace(day=actual_day)
        candidate = datetime.combine(candidate.date(), time_part)
        if timezone.is_naive(candidate):
            candidate = timezone.make_aware(candidate, timezone.get_current_timezone())

        while candidate <= now:
            candidate += relativedelta(months=n)
            max_day = calendar.monthrange(candidate.year, candidate.month)[1]
            actual_day = min(target_day, max_day)
            candidate = candidate.replace(day=actual_day)
            candidate = datetime.combine(candidate.date(), time_part)
            if timezone.is_naive(candidate):
                candidate = timezone.make_aware(candidate, timezone.get_current_timezone())

        return candidate

    @classmethod
    def _next_monthly_weekday_position(cls, reminder: "Reminder", now: datetime) -> datetime:
        """
        Nth weekday of the month (e.g. "first Monday", "last Friday").
        """
        week_pos = reminder.monthly_week or "first"
        weekday_name = reminder.monthly_weekday or "monday"
        target_weekday = WEEKDAY_MAP.get(weekday_name, 0)
        n = reminder.repeat_interval or 1

        current_dt = reminder.reminder_datetime
        time_part = current_dt.timetz()

        # Start searching from the next month
        search = current_dt + relativedelta(months=n)

        for _ in range(24):  # safety bound — 2 years
            candidate_date = cls._find_weekday_in_month(
                search.year, search.month, target_weekday, week_pos
            )
            if candidate_date is not None:
                candidate_dt = datetime.combine(candidate_date, time_part)
                if timezone.is_naive(candidate_dt):
                    candidate_dt = timezone.make_aware(candidate_dt, timezone.get_current_timezone())
                if candidate_dt > now:
                    return candidate_dt

            search += relativedelta(months=n)

        # Fallback
        return current_dt + relativedelta(months=n)

    @staticmethod
    def _find_weekday_in_month(
        year: int,
        month: int,
        weekday: int,
        position: str,
    ) -> date | None:
        """
        Find the Nth occurrence of a weekday in a given month.

        position: "first", "second", "third", "fourth", "last"
        weekday: 0=Monday … 6=Sunday
        """
        # Get all days of the month that match the target weekday
        cal = calendar.Calendar(firstweekday=0)
        matching_days = [
            d
            for d in cal.itermonthdays2(year, month)
            if d[0] != 0 and d[1] == weekday
        ]

        if not matching_days:
            return None

        position_map = {
            "first": 0,
            "second": 1,
            "third": 2,
            "fourth": 3,
            "last": -1,
        }

        idx = position_map.get(position, 0)
        try:
            day_num = matching_days[idx][0]
        except IndexError:
            return None

        return date(year, month, day_num)

    # ------------------------------------------------------------------
    # Yearly recurrence
    # ------------------------------------------------------------------

    @classmethod
    def _next_yearly(cls, reminder: "Reminder", now: datetime) -> datetime:
        """
        Same date every year. Handles Feb 29 gracefully.
        """
        n = reminder.repeat_interval or 1
        next_dt = reminder.reminder_datetime + relativedelta(years=n)

        while next_dt <= now:
            next_dt += relativedelta(years=n)

        return next_dt
