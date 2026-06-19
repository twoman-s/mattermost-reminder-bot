"""
Service for executing reminders and managing their lifecycle.

Delegates recurrence calculation to RecurrenceService.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from reminders.models import Reminder, ReminderStatus, RepeatType
from reminders.services.mattermost_service import MattermostService
from reminders.services.recurrence_service import RecurrenceService

logger = logging.getLogger(__name__)


class ReminderExecutionService:
    """
    Handles reminder delivery and lifecycle management.

    Responsibilities:
      - Format and send the reminder message to Mattermost
      - Increment occurrence_count
      - Delegate next-occurrence calculation to RecurrenceService
      - Check end conditions and complete reminders when appropriate
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
          2. Increment occurrence_count
          3. Update last_triggered_at
          4. Complete or reschedule depending on recurrence
        """
        self._send_reminder_message(reminder)

        reminder.last_triggered_at = timezone.now()
        reminder.occurrence_count += 1

        if reminder.repeat_type == RepeatType.NONE:
            # One-time reminder — done
            reminder.status = ReminderStatus.COMPLETED
            reminder.completed_at = timezone.now()
            logger.info("Reminder %s completed (one-off).", reminder.external_id)
        else:
            # Recurring — calculate next occurrence
            next_dt = RecurrenceService.calculate_next_occurrence(reminder)

            if next_dt is None:
                # Recurrence ended (end date passed or max occurrences reached)
                reminder.status = ReminderStatus.COMPLETED
                reminder.completed_at = timezone.now()
                logger.info(
                    "Reminder %s completed (recurrence ended after %d occurrences).",
                    reminder.external_id,
                    reminder.occurrence_count,
                )
            else:
                reminder.reminder_datetime = next_dt
                reminder.reminder_date = next_dt.date()
                logger.info(
                    "Reminder %s rescheduled to %s (occurrence #%d, %s).",
                    reminder.external_id,
                    next_dt,
                    reminder.occurrence_count,
                    reminder.recurrence_summary(),
                )

        reminder.save()
        return reminder

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

        if reminder.is_recurring:
            lines.append(f"\n**Repeats:** {reminder.recurrence_summary()}")

            # Show occurrence info
            if not reminder.repeat_forever and reminder.repeat_end_after:
                lines.append(
                    f"**Occurrence:** {reminder.occurrence_count + 1}/{reminder.repeat_end_after}"
                )

        message = "\n".join(lines)
        self.mm.send_reminder_channel_message(message)
