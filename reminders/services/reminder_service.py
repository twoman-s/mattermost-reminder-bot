"""
Service for executing reminders and managing recurring schedules.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from reminders.models import Reminder, ReminderStatus, RepeatType
from reminders.services.mattermost_service import MattermostService

logger = logging.getLogger(__name__)


class ReminderExecutionService:
    """
    Handles reminder delivery and lifecycle management.

    Responsibilities:
      - Format and send the reminder message to Mattermost
      - Mark one-off reminders as completed
      - Advance recurring reminders to their next occurrence
    """

    def __init__(self, mattermost_service: MattermostService | None = None) -> None:
        self.mm = mattermost_service or MattermostService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def trigger_reminder(self, reminder: Reminder) -> Reminder:
        """
        Execute a single reminder:
          1. Send the Mattermost message
          2. Update last_triggered_at
          3. Complete or reschedule depending on repeat_type
        """
        self._send_reminder_message(reminder)

        reminder.last_triggered_at = timezone.now()

        if reminder.repeat_type == RepeatType.NONE:
            reminder.status = ReminderStatus.COMPLETED
            reminder.completed_at = timezone.now()
            logger.info("Reminder %s completed (one-off).", reminder.external_id)
        else:
            next_dt = self.calculate_next_occurrence(
                current_datetime=reminder.reminder_datetime,
                repeat_type=reminder.repeat_type,
            )
            reminder.reminder_datetime = next_dt
            reminder.reminder_date = next_dt.date()
            logger.info(
                "Reminder %s rescheduled to %s (%s).",
                reminder.external_id,
                next_dt,
                reminder.repeat_type,
            )

        reminder.save()
        return reminder

    # ------------------------------------------------------------------
    # Recurring logic
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_next_occurrence(
        current_datetime,
        repeat_type: str,
    ):
        """
        Calculate the next occurrence based on the repeat type.

        Uses timezone-aware datetimes throughout. Falls back to
        ``dateutil.relativedelta`` for month/year arithmetic to
        correctly handle variable-length months and leap years.
        """
        now = timezone.now()

        mapping = {
            RepeatType.HOURLY: lambda dt: dt + timedelta(hours=1),
            RepeatType.DAILY: lambda dt: dt + timedelta(days=1),
            RepeatType.WEEKLY: lambda dt: dt + timedelta(weeks=1),
            RepeatType.MONTHLY: lambda dt: dt + relativedelta(months=1),
            RepeatType.YEARLY: lambda dt: dt + relativedelta(years=1),
        }

        advance = mapping.get(repeat_type)
        if advance is None:
            raise ValueError(f"Unknown repeat_type: {repeat_type}")

        next_dt = advance(current_datetime)

        # If the calculated next occurrence is still in the past (e.g. the
        # cron was delayed), keep advancing until it is in the future.
        while next_dt <= now:
            next_dt = advance(next_dt)

        return next_dt

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

        message = "\n".join(lines)
        self.mm.send_reminder_channel_message(message)
