"""
Reminder model for the ReminderBot application.
"""

import uuid
from django.db import models


class RepeatType(models.TextChoices):
    """Repeat type choices for reminders."""

    NONE = "none", "One Time"
    INTERVAL = "interval", "Interval"
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
    Reminder model storing all reminder data with dynamic recurrence support.
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

    repeat_interval = models.PositiveIntegerField(
        default=1,
        help_text="Interval value for repetition.",
    )

    repeat_unit = models.CharField(
        max_length=20,
        choices=[
            ("minute", "Minute"),
            ("hour", "Hour"),
            ("day", "Day"),
            ("week", "Week"),
            ("month", "Month"),
            ("year", "Year"),
        ],
        blank=True,
        default="",
        help_text="Unit for repetition interval.",
    )

    repeat_weekdays = models.JSONField(
        default=list,
        blank=True,
        help_text="List of weekdays for weekly repeat (e.g. ['monday', 'friday']).",
    )

    monthly_mode = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Monthly recurrence mode: day_of_month or weekday_position.",
    )

    monthly_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Day of month for monthly repeat.",
    )

    monthly_week = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Week position for monthly repeat: first, second, third, fourth, last.",
    )

    monthly_weekday = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Weekday for monthly repeat: monday, ..., sunday.",
    )

    yearly_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Month number (1-12) for yearly repeat.",
    )

    yearly_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Day number (1-31) for yearly repeat.",
    )

    repeat_forever = models.BooleanField(
        default=True,
        help_text="Whether the recurrence repeats indefinitely.",
    )

    repeat_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="End date for the recurrence.",
    )

    repeat_end_after = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="End recurrence after N occurrences.",
    )

    occurrence_count = models.PositiveIntegerField(
        default=0,
        help_text="Count of how many times this reminder has triggered.",
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
