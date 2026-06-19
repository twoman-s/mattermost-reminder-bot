"""
Service for executing reminders, sending notifications, and advancing schedules.
"""

from __future__ import annotations

import logging
from django.utils import timezone

from reminders.models import Reminder, ReminderStatus, RepeatType
from reminders.services.mattermost import MattermostService
from reminders.services.recurrence import RecurrenceService

logger = logging.getLogger(__name__)


class ReminderExecutionService:
    """
    Handles reminder delivery and lifecycle management.
    """

    def __init__(self, mattermost_service: MattermostService | None = None) -> None:
        self.mm = mattermost_service or MattermostService()

    @classmethod
    def execute(cls, reminder: Reminder) -> Reminder:
        """
        Class method to execute the reminder using a default service instance.
        """
        return cls()._execute_instance(reminder)

    def _execute_instance(self, reminder: Reminder) -> Reminder:
        """
        Execute a single reminder:
          1. Send the Mattermost message
          2. Update last_triggered_at
          3. Increment occurrence_count
          4. Check recurrence end conditions and reschedule
        """
        logger.info("Processing reminder: %s", reminder.title)

        # 1. Send Mattermost message
        try:
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
            logger.info("Message delivered successfully")
        except Exception as e:
            logger.error(
                "Mattermost delivery failed for reminder %s (ID: %s): %s",
                reminder.title,
                reminder.external_id,
                str(e),
                exc_info=True
            )
            # Retain original behavior: let caller catch and retry later
            raise

        # 2. Update last_triggered_at
        reminder.last_triggered_at = timezone.now()

        # 3. Increment occurrence_count
        reminder.occurrence_count += 1

        # 4. Check recurrence end conditions
        if reminder.repeat_type == RepeatType.NONE:
            # One-time reminder
            reminder.status = ReminderStatus.COMPLETED
            reminder.completed_at = timezone.now()
            reminder.next_run_at = None
            logger.info("Next occurrence: None")
            logger.info("Completion Status: Completed")
        else:
            # Check occurrence limit before calculating next occurrence
            if not reminder.repeat_forever and reminder.repeat_end_after is not None:
                if reminder.occurrence_count >= reminder.repeat_end_after:
                    reminder.status = ReminderStatus.COMPLETED
                    reminder.completed_at = timezone.now()
                    reminder.next_run_at = None
                    logger.info("Next occurrence: None")
                    logger.info("Completion Status: Completed")
                    reminder.save()
                    return reminder

            # Calculate next occurrence
            next_dt = RecurrenceService.calculate_next_occurrence(reminder)

            if next_dt is None:
                reminder.status = ReminderStatus.COMPLETED
                reminder.completed_at = timezone.now()
                reminder.next_run_at = None
                logger.info("Next occurrence: None")
                logger.info("Completion Status: Completed")
            else:
                # Check end date limit
                if not reminder.repeat_forever and reminder.repeat_end_date is not None:
                    if next_dt.date() > reminder.repeat_end_date:
                        reminder.status = ReminderStatus.COMPLETED
                        reminder.completed_at = timezone.now()
                        reminder.next_run_at = None
                        logger.info("Next occurrence: None")
                        logger.info("Completion Status: Completed")
                        reminder.save()
                        return reminder

                # Reschedule
                reminder.reminder_datetime = next_dt
                reminder.next_run_at = next_dt
                reminder.status = ReminderStatus.PENDING
                logger.info("Next occurrence: %s", next_dt.strftime("%Y-%m-%d %H:%M"))
                logger.info("Completion Status: Pending")

        reminder.save()
        return reminder
