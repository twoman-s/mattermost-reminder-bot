"""
Views for the reminders app.

Split into three groups:
  1. REST API views (DRF ViewSets) — consumed by n8n and general clients
  2. Mattermost webhook views — handle slash commands, dialog refreshes, and submissions
"""

from __future__ import annotations

import logging
from datetime import datetime

import dateutil.parser
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from reminders.models import Reminder, ReminderStatus, RepeatType
from reminders.serializers import (
    PendingReminderSerializer,
    ReminderSerializer,
    TriggerResponseSerializer,
)
from reminders.services import MattermostService, ReminderExecutionService

logger = logging.getLogger(__name__)


# ======================================================================
# REST API ViewSet
# ======================================================================


@extend_schema_view(
    list=extend_schema(tags=["Reminders"], summary="List all reminders"),
    retrieve=extend_schema(tags=["Reminders"], summary="Retrieve a reminder"),
    create=extend_schema(tags=["Reminders"], summary="Create a reminder"),
    update=extend_schema(tags=["Reminders"], summary="Update a reminder"),
    partial_update=extend_schema(tags=["Reminders"], summary="Partially update a reminder"),
    destroy=extend_schema(tags=["Reminders"], summary="Delete a reminder"),
)
class ReminderViewSet(viewsets.ModelViewSet):
    """
    Standard CRUD ViewSet for Reminder objects.

    Uses ``external_id`` (UUID) as the lookup field so internal
    auto-increment IDs are never exposed.
    """

    queryset = Reminder.objects.all()
    serializer_class = ReminderSerializer
    lookup_field = "external_id"
    permission_classes = [AllowAny]

    def create(self, request: Request, *args, **kwargs) -> Response:
        logger.info("API create reminder — data: %s", request.data)
        response = super().create(request, *args, **kwargs)
        logger.info("Reminder created via API — external_id: %s", response.data.get("external_id"))
        return response

    def update(self, request: Request, *args, **kwargs) -> Response:
        logger.info("API update reminder — external_id: %s, data: %s", kwargs.get("external_id"), request.data)
        response = super().update(request, *args, **kwargs)
        logger.info("Reminder updated via API — external_id: %s", response.data.get("external_id"))
        return response

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        logger.info("API partial update — external_id: %s, data: %s", kwargs.get("external_id"), request.data)
        response = super().partial_update(request, *args, **kwargs)
        logger.info("Reminder patched via API — external_id: %s", response.data.get("external_id"))
        return response

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        external_id = kwargs.get("external_id")
        logger.info("API delete reminder — external_id: %s", external_id)
        response = super().destroy(request, *args, **kwargs)
        logger.info("Reminder deleted via API — external_id: %s", external_id)
        return response


# ======================================================================
# n8n Integration Endpoints
# ======================================================================


class PendingRemindersView(APIView):
    """
    GET /api/v1/reminders/pending/

    Returns all reminders that are due (pending + datetime <= now).
    Consumed by n8n to discover which reminders need triggering.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["n8n Integration"],
        summary="Get due reminders",
        description="Return all pending reminders whose reminder_datetime is in the past or now.",
        responses={200: PendingReminderSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        now = timezone.now()
        reminders = Reminder.objects.filter(
            status=ReminderStatus.PENDING,
            reminder_datetime__lte=now,
        )
        serializer = PendingReminderSerializer(reminders, many=True)
        logger.info("Pending reminders query — found %d due (as of %s).", reminders.count(), now)
        return Response(serializer.data)


class TriggerReminderView(APIView):
    """
    POST /api/v1/reminders/<external_id>/trigger/

    Called by n8n to fire a specific reminder.
    All Mattermost communication happens inside Django — n8n never
    talks to Mattermost directly.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["n8n Integration"],
        summary="Trigger a reminder",
        description=(
            "Send the reminder message to Mattermost, update its state, "
            "and reschedule if recurring."
        ),
        responses={
            200: TriggerResponseSerializer,
            404: OpenApiResponse(description="Reminder not found."),
        },
    )
    def post(self, request: Request, external_id: str) -> Response:
        logger.info("Trigger requested — external_id: %s", external_id)
        try:
            reminder = Reminder.objects.get(
                external_id=external_id,
                status=ReminderStatus.PENDING,
            )
        except Reminder.DoesNotExist:
            logger.warning("Trigger failed — reminder %s not found or not pending.", external_id)
            return Response(
                {"detail": "Reminder not found or not pending."},
                status=status.HTTP_404_NOT_FOUND,
            )

        service = ReminderExecutionService()
        try:
            reminder = service.trigger_reminder(reminder)
        except Exception:
            logger.error("Trigger execution failed — external_id: %s", external_id, exc_info=True)
            return Response(
                {"detail": "Failed to trigger reminder."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "Trigger complete — external_id: %s, new_status: %s, next_datetime: %s",
            reminder.external_id,
            reminder.status,
            reminder.reminder_datetime,
        )
        serializer = TriggerResponseSerializer(reminder)
        return Response(serializer.data)


# ======================================================================
# Mattermost Webhook Views
# ======================================================================


class SlashRemindView(APIView):
    """
    POST /mattermost/slash/remind/

    Receives the Mattermost slash-command payload and immediately
    opens an Interactive Dialog for reminder creation.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle /remind slash command",
        description="Opens the Create Reminder interactive dialog in Mattermost.",
        responses={200: OpenApiResponse(description="Empty 200 — dialog opened.")},
    )
    def post(self, request: Request) -> Response:
        trigger_id: str = request.data.get("trigger_id", "")
        user_id: str = request.data.get("user_id", "unknown")
        channel_id: str = request.data.get("channel_id", "unknown")

        logger.info(
            "Slash /remind received — trigger_id: %s, user: %s, channel: %s",
            trigger_id,
            user_id,
            channel_id,
        )

        if not trigger_id:
            logger.warning("Slash command received without trigger_id — payload: %s", request.data)
            return Response(
                {"text": "Missing trigger_id. Please try again."},
                status=status.HTTP_200_OK,
            )

        # Build callback and refresh URLs
        callback_url = request.build_absolute_uri("/nudgy/mattermost/dialog/submit/")
        refresh_url = request.build_absolute_uri("/nudgy/mattermost/dialog/refresh/")
        logger.debug("Dialog urls — callback: %s, refresh: %s", callback_url, refresh_url)

        mm_service = MattermostService()
        dialog_request = mm_service.open_reminder_dialog(
            trigger_id=trigger_id,
            callback_url=callback_url,
            refresh_url=refresh_url,
        )

        try:
            mm_service.post_open_dialog(dialog_request)
        except Exception:
            logger.error(
                "Failed to open Mattermost dialog — trigger_id: %s",
                trigger_id,
                exc_info=True,
            )
            return Response(
                {"text": "Failed to open reminder dialog. Please try again."},
                status=status.HTTP_200_OK,
            )

        logger.info("Dialog opened successfully for user %s.", user_id)
        return Response(status=status.HTTP_200_OK)


class DialogRefreshView(APIView):
    """
    POST /mattermost/dialog/refresh/

    Handles dynamic updates as the user configures recurrence settings.
    Inspects current values and returns the new set of elements.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle dialog dynamic refresh",
        description="Returns an updated dialog structure based on current selected values.",
        responses={200: OpenApiResponse(description="Form representation JSON.")},
    )
    def post(self, request: Request) -> Response:
        payload = request.data
        submission: dict = payload.get("submission", {})
        logger.info("Dialog refresh request received. Submission: %s", submission)

        refresh_url = request.build_absolute_uri("/nudgy/mattermost/dialog/refresh/")

        mm_service = MattermostService()
        elements = mm_service.build_dialog_elements(submission)

        return Response({
            "type": "form",
            "form": {
                "callback_id": "create_reminder",
                "title": "Create Reminder",
                "submit_label": "Save",
                "source_url": refresh_url,
                "elements": elements,
            }
        }, status=status.HTTP_200_OK)


class DialogSubmitView(APIView):
    """
    POST /mattermost/dialog/submit/

    Receives the Interactive Dialog submission from Mattermost,
    validates input, creates the Reminder, and sends a confirmation
    message back to the user's channel.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle dialog submission",
        description="Validates and saves a new reminder from the Mattermost dialog.",
        responses={200: OpenApiResponse(description="Confirmation or validation errors.")},
    )
    def post(self, request: Request) -> Response:
        payload = request.data
        submission: dict = payload.get("submission", {})
        user_id: str = payload.get("user_id", "")
        channel_id: str = payload.get("channel_id", "")

        logger.info(
            "Dialog submission received — user: %s, channel: %s, submission: %s",
            user_id,
            channel_id,
            submission,
        )

        errors: dict[str, str] = {}

        # 1. Title Validation
        title = (submission.get("title") or "").strip()
        if not title:
            errors["title"] = "Reminder title is required."

        # 2. Datetime Picker Validation
        dt_str = (submission.get("reminder_datetime") or "").strip()
        reminder_dt = None
        if not dt_str:
            errors["reminder_datetime"] = "Reminder time is required."
        else:
            try:
                # Mattermost sends ISO/RFC3339 string (e.g. 2024-03-15T14:30:00-05:00)
                reminder_dt = dateutil.parser.parse(dt_str)
                # Convert naive to aware just in case (though it should be aware)
                if timezone.is_naive(reminder_dt):
                    reminder_dt = timezone.make_aware(reminder_dt, timezone.get_current_timezone())

                # Prevent past dates
                now = timezone.now()
                if reminder_dt < now:
                    errors["reminder_datetime"] = "Reminder time cannot be in the past."
            except Exception:
                errors["reminder_datetime"] = "Invalid date/time format."

        # 3. Recurrence Logic & Validation
        repeat_type = submission.get("repeat_type") or "none"
        description = (submission.get("description") or "").strip()

        # Fields to store
        repeat_interval = 1
        repeat_unit = ""
        repeat_weekdays = []
        monthly_mode = ""
        monthly_day = None
        monthly_week = ""
        monthly_weekday = ""
        yearly_month = None
        yearly_day = None
        repeat_forever = True
        repeat_end_date = None
        repeat_end_after = None

        if repeat_type == RepeatType.INTERVAL:
            try:
                repeat_interval = int(submission.get("repeat_interval") or 1)
                if repeat_interval <= 0:
                    errors["repeat_interval"] = "Interval must be greater than 0."
            except ValueError:
                errors["repeat_interval"] = "Interval must be a valid positive integer."

            repeat_unit = submission.get("repeat_unit") or "day"
            if repeat_unit not in ["minute", "hour", "day", "week", "month", "year"]:
                errors["repeat_unit"] = "Invalid repeat unit."

        elif repeat_type == RepeatType.WEEKLY:
            weekdays_raw = submission.get("repeat_weekdays")
            if isinstance(weekdays_raw, list):
                repeat_weekdays = weekdays_raw
            elif isinstance(weekdays_raw, str):
                repeat_weekdays = [w.strip() for w in weekdays_raw.split(",") if w.strip()]
            else:
                repeat_weekdays = []

            if not repeat_weekdays:
                errors["repeat_weekdays"] = "Please select at least one weekday."

        elif repeat_type == RepeatType.MONTHLY:
            monthly_mode = submission.get("monthly_mode") or "day_of_month"
            if monthly_mode == "day_of_month":
                try:
                    monthly_day = int(submission.get("monthly_day") or 15)
                    if not (1 <= monthly_day <= 31):
                        errors["monthly_day"] = "Day must be between 1 and 31."
                except ValueError:
                    errors["monthly_day"] = "Day must be a valid integer."
            elif monthly_mode == "weekday_position":
                monthly_week = submission.get("monthly_week") or "first"
                monthly_weekday = submission.get("monthly_weekday") or "monday"
                if monthly_week not in ["first", "second", "third", "fourth", "last"]:
                    errors["monthly_week"] = "Invalid week selector."
                if monthly_weekday not in [
                    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
                ]:
                    errors["monthly_weekday"] = "Invalid weekday selector."
            else:
                errors["monthly_mode"] = "Invalid monthly mode."

        elif repeat_type == RepeatType.YEARLY:
            try:
                yearly_month = int(submission.get("yearly_month") or 1)
                if not (1 <= yearly_month <= 12):
                    errors["yearly_month"] = "Month must be between 1 and 12."
            except ValueError:
                errors["yearly_month"] = "Month must be a valid integer."

            try:
                yearly_day = int(submission.get("yearly_day") or 1)
                if not (1 <= yearly_day <= 31):
                    errors["yearly_day"] = "Day must be between 1 and 31."
            except ValueError:
                errors["yearly_day"] = "Day must be a valid integer."

        # Parse End Conditions
        if repeat_type != "none":
            repeat_until = submission.get("repeat_until") or "forever"
            if repeat_until == "forever":
                repeat_forever = True
            elif repeat_until == "end_date":
                repeat_forever = False
                end_date_str = submission.get("repeat_end_date")
                if not end_date_str:
                    errors["repeat_end_date"] = "End date is required."
                else:
                    try:
                        repeat_end_date = parse_date(end_date_str)
                        if repeat_end_date is None:
                            errors["repeat_end_date"] = "Invalid date format. Use YYYY-MM-DD."
                        elif reminder_dt and repeat_end_date < reminder_dt.date():
                            errors["repeat_end_date"] = "End date cannot be before reminder date."
                    except Exception:
                        errors["repeat_end_date"] = "Invalid date format. Use YYYY-MM-DD."
            elif repeat_until == "end_after":
                repeat_forever = False
                try:
                    repeat_end_after = int(submission.get("repeat_end_after") or 10)
                    if repeat_end_after <= 0:
                        errors["repeat_end_after"] = "Occurrences count must be greater than 0."
                except ValueError:
                    errors["repeat_end_after"] = "Occurrences count must be a valid integer."

        if errors:
            logger.warning("Dialog validation failed — user: %s, errors: %s", user_id, errors)
            return Response({"errors": errors}, status=status.HTTP_200_OK)

        # Create the reminder
        reminder = Reminder.objects.create(
            mattermost_user_id=user_id,
            title=title,
            description=description,
            reminder_datetime=reminder_dt,
            repeat_type=repeat_type,
            repeat_interval=repeat_interval,
            repeat_unit=repeat_unit,
            repeat_weekdays=repeat_weekdays,
            monthly_mode=monthly_mode,
            monthly_day=monthly_day,
            monthly_week=monthly_week,
            monthly_weekday=monthly_weekday,
            yearly_month=yearly_month,
            yearly_day=yearly_day,
            repeat_forever=repeat_forever,
            repeat_end_date=repeat_end_date,
            repeat_end_after=repeat_end_after,
        )

        logger.info(
            "Reminder created from dialog — external_id: %s, title: '%s', "
            "datetime: %s, repeat: %s, user: %s",
            reminder.external_id,
            reminder.title,
            reminder.reminder_datetime,
            reminder.repeat_type,
            user_id,
        )

        # Send confirmation message
        mm_service = MattermostService()
        confirmation = (
            f"✅ **Reminder saved successfully.**\n\n"
            f"**Title:** {reminder.title}\n"
            f"**When:** {reminder.reminder_datetime:%Y-%m-%d %H:%M}\n"
            f"**Repeats:** {reminder.get_repeat_type_display()}"
        )

        try:
            if channel_id:
                mm_service.send_channel_message(channel_id, confirmation)
            else:
                mm_service.send_reminder_channel_message(confirmation)
            logger.info("Confirmation message sent to channel %s.", channel_id or "(default)")
        except Exception:
            logger.error(
                "Failed to send confirmation — external_id: %s, channel: %s",
                reminder.external_id,
                channel_id,
                exc_info=True,
            )

        return Response(status=status.HTTP_200_OK)
