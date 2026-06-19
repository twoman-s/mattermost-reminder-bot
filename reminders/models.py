"""
Reminder model for the ReminderBot application.

Supports a full recurrence engine similar to Google Calendar:
  - Interval-based (every N minutes/hours/days/weeks/months/years)
  - Weekly on specific weekdays
  - Monthly by day-of-month or weekday-position
  - Yearly on specific date
  - End conditions: forever, on date, or after N occurrences
"""

import uuid

from django.db import models


class RepeatType(models.TextChoices):
    """Top-level recurrence pattern category."""

    NONE = "none", "One Time"
    INTERVAL = "interval", "Interval"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    YEARLY = "yearly", "Yearly"


class RepeatUnit(models.TextChoices):
    """Unit for interval-based recurrence."""

    MINUTE = "minute", "Minute"
    HOUR = "hour", "Hour"
    DAY = "day", "Day"
    WEEK = "week", "Week"
    MONTH = "month", "Month"
    YEAR = "year", "Year"


class MonthlyMode(models.TextChoices):
    """How monthly recurrence is anchored."""

    DAY_OF_MONTH = "day_of_month", "Day Of Month"
    WEEKDAY_POSITION = "weekday_position", "Weekday Position"


class MonthlyWeek(models.TextChoices):
    """Which week-of-month for weekday-position recurrence."""

    FIRST = "first", "First"
    SECOND = "second", "Second"
    THIRD = "third", "Third"
    FOURTH = "fourth", "Fourth"
    LAST = "last", "Last"


class Weekday(models.TextChoices):
    """Standard weekday names (lowercase) used in repeat_weekdays and monthly_weekday."""

    MONDAY = "monday", "Monday"
    TUESDAY = "tuesday", "Tuesday"
    WEDNESDAY = "wednesday", "Wednesday"
    THURSDAY = "thursday", "Thursday"
    FRIDAY = "friday", "Friday"
    SATURDAY = "saturday", "Saturday"
    SUNDAY = "sunday", "Sunday"


class ReminderStatus(models.TextChoices):
    """Lifecycle status for reminders."""

    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class Reminder(models.Model):
    """
    Reminder model with a full recurrence engine.

    external_id is used as the public-facing identifier in API responses
    and Mattermost interactions, keeping the internal auto-increment ID private.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Core content
    # ------------------------------------------------------------------
    title = models.CharField(
        max_length=255,
        help_text="Short title for the reminder.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional longer description.",
    )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    reminder_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date portion of the reminder (for display / filtering).",
    )
    reminder_datetime = models.DateTimeField(
        db_index=True,
        help_text="Full date-time when the reminder should fire next.",
    )

    # ------------------------------------------------------------------
    # Recurrence — top-level
    # ------------------------------------------------------------------
    repeat_type = models.CharField(
        max_length=10,
        choices=RepeatType.choices,
        default=RepeatType.NONE,
        help_text="Top-level recurrence category.",
    )

    # ------------------------------------------------------------------
    # Recurrence — interval
    # ------------------------------------------------------------------
    repeat_interval = models.PositiveIntegerField(
        default=1,
        help_text="How many units between recurrences (e.g. 2 = every 2 …).",
    )
    repeat_unit = models.CharField(
        max_length=20,
        choices=RepeatUnit.choices,
        blank=True,
        default="",
        help_text="Unit for interval recurrence (minute, hour, day, …).",
    )

    # ------------------------------------------------------------------
    # Recurrence — weekly
    # ------------------------------------------------------------------
    repeat_weekdays = models.JSONField(
        default=list,
        blank=True,
        help_text='List of weekday names, e.g. ["monday","friday"].',
    )

    # ------------------------------------------------------------------
    # Recurrence — monthly
    # ------------------------------------------------------------------
    monthly_mode = models.CharField(
        max_length=30,
        choices=MonthlyMode.choices,
        blank=True,
        default="",
        help_text="Whether to anchor monthly recurrence to a day number or weekday position.",
    )
    monthly_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Day of month (1–31) for day_of_month mode.",
    )
    monthly_week = models.CharField(
        max_length=10,
        choices=MonthlyWeek.choices,
        blank=True,
        default="",
        help_text="Which week-of-month for weekday_position mode.",
    )
    monthly_weekday = models.CharField(
        max_length=10,
        choices=Weekday.choices,
        blank=True,
        default="",
        help_text="Which weekday for weekday_position mode.",
    )

    # ------------------------------------------------------------------
    # Recurrence — end conditions
    # ------------------------------------------------------------------
    repeat_forever = models.BooleanField(
        default=True,
        help_text="If True, the recurrence never ends.",
    )
    repeat_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Stop recurrence after this date.",
    )
    repeat_end_after = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Stop recurrence after this many occurrences.",
    )
    occurrence_count = models.PositiveIntegerField(
        default=0,
        help_text="How many times this reminder has been triggered so far.",
    )

    # ------------------------------------------------------------------
    # Snooze
    # ------------------------------------------------------------------
    snooze_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Minutes to snooze when triggered (0 = no snooze).",
    )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
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

    @property
    def is_recurring(self) -> bool:
        """Return True if this reminder has any form of recurrence."""
        return self.repeat_type != RepeatType.NONE

    def recurrence_summary(self) -> str:
        """Human-readable summary of the recurrence rule."""
        if self.repeat_type == RepeatType.NONE:
            return "One time"

        if self.repeat_type == RepeatType.INTERVAL:
            unit = self.repeat_unit or "day"
            n = self.repeat_interval or 1
            unit_label = unit if n == 1 else f"{unit}s"
            return f"Every {n} {unit_label}" if n > 1 else f"Every {unit}"

        if self.repeat_type == RepeatType.WEEKLY:
            days = self.repeat_weekdays or []
            if not days:
                return "Weekly"
            return "Every " + ", ".join(d.capitalize() for d in days)

        if self.repeat_type == RepeatType.MONTHLY:
            if self.monthly_mode == MonthlyMode.DAY_OF_MONTH:
                return f"Monthly on day {self.monthly_day}"
            if self.monthly_mode == MonthlyMode.WEEKDAY_POSITION:
                week = (self.monthly_week or "").capitalize()
                day = (self.monthly_weekday or "").capitalize()
                return f"{week} {day} of every month"
            return "Monthly"

        if self.repeat_type == RepeatType.YEARLY:
            return "Yearly"

        return self.get_repeat_type_display()
