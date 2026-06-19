"""
Django admin configuration for the Reminder model.
"""

from django.contrib import admin
from reminders.models import Reminder


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    """Admin interface for managing reminders."""

    list_display = [
        "title",
        "mattermost_user_id",
        "status",
        "repeat_type",
        "reminder_datetime",
        "next_run_at",
        "occurrence_count",
        "last_triggered_at",
        "created_at",
    ]
    list_filter = [
        "status",
        "repeat_type",
        "repeat_unit",
    ]
    search_fields = [
        "title",
        "mattermost_user_id",
        "description",
    ]
    ordering = ["reminder_datetime"]
    readonly_fields = [
        "external_id",
        "next_run_at",
        "occurrence_count",
        "last_triggered_at",
        "created_at",
        "updated_at",
        "completed_at",
    ]
    list_per_page = 25
