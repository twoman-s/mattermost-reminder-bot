"""
Reminder model for the ReminderBot application.
"""

import uuid

from django.db import models


class RepeatType(models.TextChoices):
    """Repeat type choices for reminders."""

    NONE = "none", "Never"
    HOURLY = "hourly", "Hourly"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    YEARLY = "yearly", "Yearly"


class ReminderStatus(models.TextChoices):
    """Status choices for reminders."""

    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class Reminder(models.Model):
    """
    Reminder model storing all reminder data.

    external_id is used as the public-facing identifier in API responses
    and Mattermost interactions, keeping the internal auto-increment ID private.
    """

    external_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Public-facing UUID for API and Mattermost interactions.",
    )
    mattermost_user_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Mattermost user ID of the reminder creator.",
    )

    title = models.CharField(
        max_length=255,
        help_text="Short title for the reminder.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional longer description.",
    )

    reminder_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date portion of the reminder (for display / filtering).",
    )
    reminder_datetime = models.DateTimeField(
        db_index=True,
        help_text="Full date-time when the reminder should fire.",
    )

    repeat_type = models.CharField(
        max_length=10,
        choices=RepeatType.choices,
        default=RepeatType.NONE,
        help_text="Recurrence pattern for the reminder.",
    )
    snooze_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Minutes to snooze when triggered (0 = no snooze).",
    )

    status = models.CharField(
        max_length=10,
        choices=ReminderStatus.choices,
        default=ReminderStatus.PENDING,
        db_index=True,
        help_text="Current lifecycle status.",
    )

    last_triggered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the most recent trigger.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the reminder was marked completed.",
    )

    class Meta:
        ordering = ["reminder_datetime"]
        verbose_name = "Reminder"
        verbose_name_plural = "Reminders"

    def __str__(self) -> str:
        return f"[{self.status}] {self.title} — {self.reminder_datetime:%Y-%m-%d %H:%M}"
