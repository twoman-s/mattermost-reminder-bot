"""
Service for executing reminders and managing recurring schedules.
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from reminders.models import Reminder, ReminderStatus, RepeatType
from reminders.services.mattermost_service import MattermostService

logger = logging.getLogger(__name__)


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
        Calculate the next scheduled datetime for the reminder.
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


class ReminderExecutionService:
    """
    Handles reminder delivery and lifecycle management.
    """

    def __init__(self, mattermost_service: MattermostService | None = None) -> None:
        self.mm = mattermost_service or MattermostService()

    def trigger_reminder(self, reminder: Reminder) -> Reminder:
        """
        Execute a single reminder:
          1. Send the Mattermost message
          2. Update last_triggered_at
          3. Increment occurrence_count
          4. Check recurrence end conditions and reschedule
        """
        # 1. Send Mattermost message
        self._send_reminder_message(reminder)

        # 2. Update last_triggered_at
        reminder.last_triggered_at = timezone.now()

        # 3. Increment occurrence_count
        reminder.occurrence_count += 1

        # 4. Check recurrence end conditions
        if reminder.repeat_type == RepeatType.NONE:
            # One-time reminder
            reminder.status = ReminderStatus.COMPLETED
            reminder.completed_at = timezone.now()
            logger.info("Reminder %s completed (one-off).", reminder.external_id)
        else:
            # Check occurrence limit before calculating next occurrence
            if not reminder.repeat_forever and reminder.repeat_end_after is not None:
                if reminder.occurrence_count >= reminder.repeat_end_after:
                    reminder.status = ReminderStatus.COMPLETED
                    reminder.completed_at = timezone.now()
                    logger.info(
                        "Reminder %s completed (reached end occurrence count %d).",
                        reminder.external_id,
                        reminder.repeat_end_after,
                    )
                    reminder.save()
                    return reminder

            # Calculate next occurrence
            next_dt = RecurrenceService.calculate_next_occurrence(reminder)

            if next_dt is None:
                reminder.status = ReminderStatus.COMPLETED
                reminder.completed_at = timezone.now()
                logger.info("Reminder %s completed (no next occurrence).", reminder.external_id)
            else:
                # Check end date limit
                if not reminder.repeat_forever and reminder.repeat_end_date is not None:
                    if next_dt.date() > reminder.repeat_end_date:
                        reminder.status = ReminderStatus.COMPLETED
                        reminder.completed_at = timezone.now()
                        logger.info(
                            "Reminder %s completed (next occurrence %s is past end date %s).",
                            reminder.external_id,
                            next_dt,
                            reminder.repeat_end_date,
                        )
                        reminder.save()
                        return reminder

                # Reschedule
                reminder.reminder_datetime = next_dt
                reminder.status = ReminderStatus.PENDING
                logger.info(
                    "Reminder %s rescheduled to %s (occurrence #%d).",
                    reminder.external_id,
                    next_dt,
                    reminder.occurrence_count,
                )

        reminder.save()
        return reminder

    def _send_reminder_message(self, reminder: Reminder) -> None:
        """Format and send the reminder notification to Mattermost."""
        scheduled_time = reminder.reminder_datetime.strftime("%Y-%m-%d %H:%M")

        lines = [
            "⏰ **Reminder**",
            "",
            f"**Title:**\n{reminder.title}",
        ]
        if reminder.description:
            lines.append(f"\n**Description:**\n{reminder.description}")

        if reminder.mattermost_user_id:
            lines.append(f"\n**Created By:** {reminder.mattermost_user_id}")

        lines.append(f"\n**Scheduled Time:**\n{scheduled_time}")

        if reminder.repeat_type and reminder.repeat_type != RepeatType.NONE:
            lines.append(f"\n**Repeats:** {reminder.get_repeat_type_display()}")
            lines.append(f"**Occurrence:** #{reminder.occurrence_count + 1}")

        message = "\n".join(lines)
        self.mm.send_reminder_channel_message(message)
