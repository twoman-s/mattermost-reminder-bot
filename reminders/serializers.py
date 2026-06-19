"""
DRF serializers for the Reminder model.
"""

from __future__ import annotations

from rest_framework import serializers

from reminders.models import Reminder


class ReminderSerializer(serializers.ModelSerializer):
    """Full serializer used for CRUD operations."""

    class Meta:
        model = Reminder
        fields = [
            "external_id",
            "mattermost_user_id",
            "title",
            "description",
            "reminder_datetime",
            "repeat_type",
            "repeat_interval",
            "repeat_unit",
            "repeat_weekdays",
            "monthly_mode",
            "monthly_day",
            "monthly_week",
            "monthly_weekday",
            "yearly_month",
            "yearly_day",
            "repeat_forever",
            "repeat_end_date",
            "repeat_end_after",
            "occurrence_count",
            "status",
            "last_triggered_at",
            "created_at",
            "updated_at",
            "completed_at",
        ]
        read_only_fields = [
            "external_id",
            "occurrence_count",
            "last_triggered_at",
            "created_at",
            "updated_at",
            "completed_at",
        ]


class PendingReminderSerializer(serializers.ModelSerializer):
    """Lightweight serializer for the n8n polling endpoint."""

    class Meta:
        model = Reminder
        fields = [
            "external_id",
            "title",
            "description",
            "reminder_datetime",
            "repeat_type",
        ]


class TriggerResponseSerializer(serializers.ModelSerializer):
    """Serializer returned after a reminder is triggered."""

    class Meta:
        model = Reminder
        fields = [
            "external_id",
            "title",
            "status",
            "reminder_datetime",
            "repeat_type",
            "occurrence_count",
            "last_triggered_at",
            "completed_at",
        ]
