"""
Views for the reminders app.

Split into three groups:
  1. REST API views (DRF ViewSets) — consumed by n8n and general clients
  2. Mattermost webhook views — handle slash commands and dialog submissions
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from reminders.models import Reminder, ReminderStatus
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

        # Build the callback URL that Mattermost will POST the dialog
        # submission to. We use the request to derive the host.
        callback_url = request.build_absolute_uri("/nudgy/mattermost/dialog/submit/")
        logger.debug("Dialog callback URL: %s", callback_url)

        mm_service = MattermostService()
        dialog_request = mm_service.open_reminder_dialog(trigger_id)
        dialog_request["url"] = callback_url

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
        # Mattermost expects a 200 with empty body (or optional ephemeral text).
        return Response(status=status.HTTP_200_OK)


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

        # --- Validate required fields ---
        errors: dict[str, str] = {}

        title = (submission.get("title") or "").strip()
        if not title:
            errors["title"] = "Reminder title is required."

        date_str = (submission.get("reminder_date") or "").strip()
        time_str = (submission.get("reminder_time") or "").strip()

        if not date_str:
            errors["reminder_date"] = "Reminder date is required."
        if not time_str:
            errors["reminder_time"] = "Reminder time is required."

        # Parse date + time
        reminder_dt = None
        if date_str and time_str:
            try:
                naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                reminder_dt = timezone.make_aware(naive_dt, timezone.get_current_timezone())
            except ValueError:
                errors["reminder_date"] = "Invalid date/time format. Use YYYY-MM-DD and HH:MM."

        if errors:
            logger.warning("Dialog validation failed — user: %s, errors: %s", user_id, errors)
            # Mattermost expects {"errors": {...}} to display inline validation.
            return Response({"errors": errors}, status=status.HTTP_200_OK)

        # --- Create the reminder ---
        description = (submission.get("description") or "").strip()
        repeat_type = submission.get("repeat_type", "none")
        snooze_minutes = int(submission.get("snooze_minutes", 0) or 0)

        reminder = Reminder.objects.create(
            mattermost_user_id=user_id,
            title=title,
            description=description,
            reminder_date=reminder_dt.date(),
            reminder_datetime=reminder_dt,
            repeat_type=repeat_type,
            snooze_minutes=snooze_minutes,
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

        # --- Send confirmation back ---
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

        # Return empty 200 so Mattermost doesn't show an error.
        return Response(status=status.HTTP_200_OK)
