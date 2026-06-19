"""
Django admin configuration for the Reminder model.
"""

from django.contrib import admin

from reminders.models import Reminder


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    """Admin interface for managing reminders with full recurrence support."""

    list_display = [
        "title",
        "mattermost_user_id",
        "status",
        "repeat_type",
        "recurrence_display",
        "reminder_datetime",
        "occurrence_count",
        "last_triggered_at",
        "created_at",
    ]
    list_filter = [
        "status",
        "repeat_type",
        "repeat_forever",
        "monthly_mode",
    ]
    search_fields = [
        "title",
        "mattermost_user_id",
        "description",
    ]
    ordering = ["reminder_datetime"]
    readonly_fields = [
        "external_id",
        "occurrence_count",
        "last_triggered_at",
        "created_at",
        "updated_at",
        "completed_at",
        "recurrence_display",
    ]
    list_per_page = 25

    fieldsets = (
        ("Core", {
            "fields": (
                "external_id",
                "mattermost_user_id",
                "title",
                "description",
            ),
        }),
        ("Scheduling", {
            "fields": (
                "reminder_date",
                "reminder_datetime",
                "snooze_minutes",
            ),
        }),
        ("Recurrence", {
            "fields": (
                "repeat_type",
                "repeat_interval",
                "repeat_unit",
                "repeat_weekdays",
                "monthly_mode",
                "monthly_day",
                "monthly_week",
                "monthly_weekday",
                "recurrence_display",
            ),
        }),
        ("End Conditions", {
            "fields": (
                "repeat_forever",
                "repeat_end_date",
                "repeat_end_after",
                "occurrence_count",
            ),
        }),
        ("Lifecycle", {
            "fields": (
                "status",
                "last_triggered_at",
                "created_at",
                "updated_at",
                "completed_at",
            ),
        }),
    )

    @admin.display(description="Recurrence")
    def recurrence_display(self, obj: Reminder) -> str:
        return obj.recurrence_summary()
