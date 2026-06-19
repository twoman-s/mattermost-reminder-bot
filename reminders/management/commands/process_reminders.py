"""
Django management command to find and process due reminders.
"""

from __future__ import annotations

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from reminders.models import Reminder, ReminderStatus
from reminders.services.execution import ReminderExecutionService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Command to process all pending reminders whose next_run_at is in the past.
    Designed to run safely and idempotently via cron.
    """

    help = "Find due reminders and execute them."

    def handle(self, *args: list, **options: dict) -> None:
        now = timezone.now()

        # Find candidate pending reminders
        due_reminders = Reminder.objects.filter(
            status=ReminderStatus.PENDING,
            next_run_at__lte=now,
        ).order_by("next_run_at")

        count = due_reminders.count()
        if count == 0:
            logger.debug("No due reminders found.")
            return

        logger.info("Found %d due reminders to process.", count)

        for reminder in due_reminders:
            try:
                # Wrap each execution in a transaction block
                with transaction.atomic():
                    # Re-fetch the row with a write lock to prevent race conditions
                    locked_reminder = Reminder.objects.select_for_update().get(pk=reminder.pk)

                    # Verify eligibility again inside lock
                    if locked_reminder.status != ReminderStatus.PENDING:
                        logger.warning(
                            "Skipping reminder %s: status changed to %s",
                            locked_reminder.external_id,
                            locked_reminder.status,
                        )
                        continue

                    if locked_reminder.next_run_at > timezone.now():
                        logger.warning(
                            "Skipping reminder %s: next_run_at changed to future time %s",
                            locked_reminder.external_id,
                            locked_reminder.next_run_at,
                        )
                        continue

                    # Execute execution workflow (sends message, updates next_run_at/status)
                    ReminderExecutionService.execute(locked_reminder)

            except Exception as e:
                logger.error(
                    "Error executing reminder %s: %s",
                    reminder.external_id,
                    str(e),
                    exc_info=True,
                )
