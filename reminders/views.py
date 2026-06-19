"""
Views for the reminders app.

Split into three groups:
  1. REST API views (DRF ViewSets) — consumed by n8n and general clients
  2. Mattermost webhook views — slash commands, dialog submissions, dialog refresh
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

        callback_url = request.build_absolute_uri("/nudgy/mattermost/dialog/submit/")
        logger.debug("Dialog callback URL: %s", callback_url)

        mm_service = MattermostService()
        dialog_request = mm_service.build_reminder_dialog(
            trigger_id=trigger_id,
            callback_url=callback_url,
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

    Handles Mattermost Interactive Dialog refresh callbacks.
    When a user changes the repeat_type field, Mattermost POSTs
    the current submission here and expects updated dialog elements
    in response.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle dialog field refresh",
        description="Returns updated dialog elements based on current field selections.",
        responses={200: OpenApiResponse(description="Updated dialog elements.")},
    )
    def post(self, request: Request) -> Response:
        payload = request.data
        submission: dict = payload.get("submission", {})

        logger.info("Dialog refresh received — submission: %s", submission)

        callback_url = request.build_absolute_uri("/nudgy/mattermost/dialog/submit/")

        mm_service = MattermostService()
        repeat_type = submission.get("repeat_type", "none")
        elements = mm_service._build_dialog_elements(repeat_type, submission)

        # Mattermost expects a partial dialog response with updated elements
        response_payload = {
            "update": {
                "title": "Create Reminder",
                "submit_label": "Save",
                "elements": elements,
            },
        }

        logger.info("Dialog refresh response — %d elements for repeat_type=%s.", len(elements), repeat_type)
        return Response(response_payload, status=status.HTTP_200_OK)


class DialogSubmitView(APIView):
    """
    POST /mattermost/dialog/submit/

    Receives the Interactive Dialog submission from Mattermost,
    validates input, creates the Reminder with full recurrence
    configuration, and sends a confirmation message.
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

        # --- Validate & parse ---
        errors: dict[str, str] = {}
        reminder_kwargs = self._validate_and_parse(submission, errors)

        if errors:
            logger.warning("Dialog validation failed — user: %s, errors: %s", user_id, errors)
            return Response({"errors": errors}, status=status.HTTP_200_OK)

        # --- Create the reminder ---
        reminder = Reminder.objects.create(
            mattermost_user_id=user_id,
            **reminder_kwargs,
        )

        logger.info(
            "Reminder created from dialog — external_id: %s, title: '%s', "
            "datetime: %s, recurrence: %s, user: %s",
            reminder.external_id,
            reminder.title,
            reminder.reminder_datetime,
            reminder.recurrence_summary(),
            user_id,
        )

        # --- Send confirmation back ---
        mm_service = MattermostService()
        confirmation = (
            f"✅ **Reminder saved successfully.**\n\n"
            f"**Title:** {reminder.title}\n"
            f"**When:** {reminder.reminder_datetime:%Y-%m-%d %H:%M}\n"
            f"**Repeats:** {reminder.recurrence_summary()}"
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

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_and_parse(submission: dict, errors: dict) -> dict:
        """
        Parse and validate the dialog submission fields.
        Returns a dict of Reminder model kwargs.
        Populates ``errors`` dict with field-level error messages.
        """
        kwargs: dict = {}

        # ---- Title ----
        title = (submission.get("title") or "").strip()
        if not title:
            errors["title"] = "Reminder title is required."
        kwargs["title"] = title
        kwargs["description"] = (submission.get("description") or "").strip()

        # ---- Date + Time ----
        date_str = (submission.get("reminder_date") or "").strip()
        hour = submission.get("reminder_hour", "09")
        minute = submission.get("reminder_minute", "00")

        if not date_str:
            errors["reminder_date"] = "Reminder date is required."

        reminder_dt = None
        if date_str:
            try:
                time_str = f"{hour}:{minute}"
                naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                reminder_dt = timezone.make_aware(naive_dt, timezone.get_current_timezone())
            except ValueError:
                errors["reminder_date"] = "Invalid date format. Use YYYY-MM-DD."

        if reminder_dt:
            kwargs["reminder_date"] = reminder_dt.date()
            kwargs["reminder_datetime"] = reminder_dt
        elif not errors.get("reminder_date"):
            errors["reminder_date"] = "Could not parse reminder date/time."

        # ---- Recurrence ----
        repeat_type = submission.get("repeat_type", "none")
        kwargs["repeat_type"] = repeat_type

        if repeat_type == "interval":
            try:
                kwargs["repeat_interval"] = max(1, int(submission.get("repeat_interval", 1)))
            except (ValueError, TypeError):
                errors["repeat_interval"] = "Must be a positive number."
                kwargs["repeat_interval"] = 1

            repeat_unit = submission.get("repeat_unit", "day")
            if repeat_unit not in ("minute", "hour", "day", "week", "month", "year"):
                errors["repeat_unit"] = "Invalid unit."
            kwargs["repeat_unit"] = repeat_unit

        elif repeat_type == "weekly":
            raw_weekdays = (submission.get("repeat_weekdays") or "").strip()
            if raw_weekdays:
                weekday_list = [d.strip().lower() for d in raw_weekdays.split(",") if d.strip()]
                valid_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
                invalid = [d for d in weekday_list if d not in valid_days]
                if invalid:
                    errors["repeat_weekdays"] = f"Invalid weekday(s): {', '.join(invalid)}"
                kwargs["repeat_weekdays"] = weekday_list
            else:
                errors["repeat_weekdays"] = "Select at least one weekday."

        elif repeat_type == "monthly":
            monthly_mode = submission.get("monthly_mode", "day_of_month")
            kwargs["monthly_mode"] = monthly_mode

            if monthly_mode == "day_of_month":
                try:
                    day = int(submission.get("monthly_day", 1))
                    if day < 1 or day > 31:
                        errors["monthly_day"] = "Day must be between 1 and 31."
                    kwargs["monthly_day"] = day
                except (ValueError, TypeError):
                    errors["monthly_day"] = "Must be a number (1–31)."

            elif monthly_mode == "weekday_position":
                kwargs["monthly_week"] = submission.get("monthly_week", "first")
                kwargs["monthly_weekday"] = submission.get("monthly_weekday", "monday")

        elif repeat_type == "yearly":
            # For yearly, we store the recurrence in the reminder_datetime itself.
            # The yearly_month and yearly_day from the dialog are informational
            # for display — the actual date anchoring is via reminder_datetime.
            pass

        # ---- End conditions ----
        if repeat_type != "none":
            end_type = submission.get("repeat_end_type", "forever")

            if end_type == "forever":
                kwargs["repeat_forever"] = True
            elif end_type == "end_date":
                kwargs["repeat_forever"] = False
                end_date_str = (submission.get("repeat_end_date") or "").strip()
                if end_date_str:
                    try:
                        kwargs["repeat_end_date"] = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                    except ValueError:
                        errors["repeat_end_date"] = "Invalid date. Use YYYY-MM-DD."
                else:
                    errors["repeat_end_date"] = "End date is required."
            elif end_type == "end_after":
                kwargs["repeat_forever"] = False
                try:
                    count = int(submission.get("repeat_end_after", 10))
                    if count < 1:
                        errors["repeat_end_after"] = "Must be at least 1."
                    kwargs["repeat_end_after"] = count
                except (ValueError, TypeError):
                    errors["repeat_end_after"] = "Must be a positive number."
        else:
            kwargs["repeat_forever"] = False

        # ---- Snooze ----
        try:
            kwargs["snooze_minutes"] = int(submission.get("snooze_minutes", 0) or 0)
        except (ValueError, TypeError):
            kwargs["snooze_minutes"] = 0

        return kwargs
