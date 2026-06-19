"""
Service classes for Mattermost API communication.

All Mattermost interaction is encapsulated here so that views
and other services never call the Mattermost API directly.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class MattermostService:
    """
    Handles all communication with the Mattermost REST API.

    Responsibilities:
      - Open interactive dialogs (with dynamic refresh support)
      - Send channel / DM messages
      - Discover bot user information
      - Discover team information
    """

    def __init__(self) -> None:
        self.base_url: str = settings.MATTERMOST_URL.rstrip("/")
        self.token: str = settings.MATTERMOST_BOT_TOKEN
        self.channel_id: str = settings.MATTERMOST_REMINDER_CHANNEL_ID
        self._bot_user_id: str | None = None
        self._team_id: str | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _api(self, path: str) -> str:
        """Build a full API URL."""
        return f"{self.base_url}/api/v4{path}"

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        url = self._api(path)
        logger.debug("MM API GET %s", url)
        try:
            resp = requests.get(url, headers=self._headers, timeout=10, **kwargs)
            resp.raise_for_status()
            logger.debug("MM API GET %s — %d", url, resp.status_code)
            return resp
        except requests.RequestException:
            logger.error("MM API GET %s failed", url, exc_info=True)
            raise

    def _post(self, path: str, json: dict | None = None, **kwargs: Any) -> requests.Response:
        url = self._api(path)
        logger.debug("MM API POST %s — payload: %s", url, json)
        try:
            resp = requests.post(url, headers=self._headers, json=json, timeout=10, **kwargs)
            resp.raise_for_status()
            logger.debug("MM API POST %s — %d", url, resp.status_code)
            return resp
        except requests.RequestException:
            logger.error("MM API POST %s failed — payload: %s", url, json, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_bot_user_id(self) -> str:
        """Return the bot's Mattermost user ID, auto-discovering if needed."""
        if self._bot_user_id:
            return self._bot_user_id
        resp = self._get("/users/me")
        self._bot_user_id = resp.json()["id"]
        logger.info("Discovered bot user ID: %s", self._bot_user_id)
        return self._bot_user_id

    def get_team_id(self) -> str:
        """Return the first team the bot belongs to, auto-discovering if needed."""
        if self._team_id:
            return self._team_id
        resp = self._get("/users/me/teams")
        teams = resp.json()
        if not teams:
            raise RuntimeError("Bot user does not belong to any Mattermost team.")
        self._team_id = teams[0]["id"]
        logger.info("Discovered team ID: %s", self._team_id)
        return self._team_id

    # ------------------------------------------------------------------
    # Interactive Dialogs
    # ------------------------------------------------------------------

    def build_reminder_dialog(
        self,
        trigger_id: str,
        callback_url: str,
        submission: dict | None = None,
    ) -> dict:
        """
        Build the 'Create Reminder' interactive dialog payload.

        If ``submission`` is provided (from a refresh callback), the dialog
        elements are adjusted dynamically based on the selected repeat_type.
        """
        current = submission or {}
        repeat_type = current.get("repeat_type", "none")

        elements = self._build_dialog_elements(repeat_type, current)

        dialog_request = {
            "trigger_id": trigger_id,
            "url": callback_url,
            "dialog": {
                "callback_id": "create_reminder",
                "title": "Create Reminder",
                "submit_label": "Save",
                "elements": elements,
            },
        }
        return dialog_request

    def _build_dialog_elements(
        self, repeat_type: str, current: dict
    ) -> list[dict]:
        """
        Construct the full list of dialog elements, dynamically adding
        recurrence-specific fields based on the selected repeat_type.
        """
        elements: list[dict] = []

        # ---- Core fields ----
        elements.append({
            "display_name": "Reminder Title",
            "name": "title",
            "type": "text",
            "default": current.get("title", ""),
            "placeholder": "e.g. Pay Electricity Bill",
            "help_text": "Short title for your reminder.",
        })
        elements.append({
            "display_name": "Description",
            "name": "description",
            "type": "textarea",
            "optional": True,
            "default": current.get("description", ""),
            "placeholder": "Optional details…",
            "help_text": "Additional notes for the reminder.",
        })

        # ---- Date & Time ----
        elements.append({
            "display_name": "Reminder Date",
            "name": "reminder_date",
            "type": "text",
            "default": current.get("reminder_date", ""),
            "placeholder": "YYYY-MM-DD",
            "help_text": "Date for the reminder (e.g. 2026-06-20).",
        })

        # Time — hour dropdown
        elements.append({
            "display_name": "Hour (24h)",
            "name": "reminder_hour",
            "type": "select",
            "default": current.get("reminder_hour", "09"),
            "options": [
                {"text": f"{h:02d}", "value": f"{h:02d}"}
                for h in range(24)
            ],
            "help_text": "Hour in 24-hour format.",
        })
        # Time — minute dropdown
        elements.append({
            "display_name": "Minute",
            "name": "reminder_minute",
            "type": "select",
            "default": current.get("reminder_minute", "00"),
            "options": [
                {"text": f"{m:02d}", "value": f"{m:02d}"}
                for m in range(0, 60, 5)
            ],
            "help_text": "Minute (in 5-minute increments).",
        })

        # ---- Recurrence Type ----
        elements.append({
            "display_name": "Recurrence",
            "name": "repeat_type",
            "type": "select",
            "default": repeat_type,
            "options": [
                {"text": "One Time", "value": "none"},
                {"text": "Interval (every N …)", "value": "interval"},
                {"text": "Weekly", "value": "weekly"},
                {"text": "Monthly", "value": "monthly"},
                {"text": "Yearly", "value": "yearly"},
            ],
            "help_text": "How should this reminder repeat?",
        })

        # ---- Dynamic recurrence fields ----
        if repeat_type == "interval":
            elements.extend(self._interval_elements(current))
        elif repeat_type == "weekly":
            elements.extend(self._weekly_elements(current))
        elif repeat_type == "monthly":
            elements.extend(self._monthly_elements(current))
        elif repeat_type == "yearly":
            elements.extend(self._yearly_elements(current))

        # ---- End conditions (only for recurring) ----
        if repeat_type != "none":
            elements.extend(self._end_condition_elements(current))

        # ---- Snooze ----
        elements.append({
            "display_name": "Snooze Minutes",
            "name": "snooze_minutes",
            "type": "select",
            "default": current.get("snooze_minutes", "0"),
            "optional": True,
            "options": [
                {"text": "0", "value": "0"},
                {"text": "5", "value": "5"},
                {"text": "10", "value": "10"},
                {"text": "15", "value": "15"},
                {"text": "30", "value": "30"},
                {"text": "60", "value": "60"},
            ],
            "help_text": "Snooze duration in minutes after trigger.",
        })

        return elements

    # ------------------------------------------------------------------
    # Dynamic element builders
    # ------------------------------------------------------------------

    @staticmethod
    def _interval_elements(current: dict) -> list[dict]:
        """Fields for interval-based recurrence."""
        return [
            {
                "display_name": "Every N",
                "name": "repeat_interval",
                "type": "text",
                "subtype": "number",
                "default": current.get("repeat_interval", "1"),
                "placeholder": "e.g. 2",
                "help_text": "Repeat every N units.",
            },
            {
                "display_name": "Unit",
                "name": "repeat_unit",
                "type": "select",
                "default": current.get("repeat_unit", "day"),
                "options": [
                    {"text": "Minutes", "value": "minute"},
                    {"text": "Hours", "value": "hour"},
                    {"text": "Days", "value": "day"},
                    {"text": "Weeks", "value": "week"},
                    {"text": "Months", "value": "month"},
                    {"text": "Years", "value": "year"},
                ],
                "help_text": "Unit of the interval.",
            },
        ]

    @staticmethod
    def _weekly_elements(current: dict) -> list[dict]:
        """Fields for weekly recurrence."""
        return [
            {
                "display_name": "Weekdays",
                "name": "repeat_weekdays",
                "type": "text",
                "default": current.get("repeat_weekdays", ""),
                "placeholder": "monday,friday",
                "help_text": (
                    "Comma-separated weekday names. "
                    "Examples: monday | monday,friday | monday,tuesday,wednesday,thursday,friday"
                ),
            },
        ]

    @staticmethod
    def _monthly_elements(current: dict) -> list[dict]:
        """Fields for monthly recurrence."""
        monthly_mode = current.get("monthly_mode", "day_of_month")
        elements: list[dict] = [
            {
                "display_name": "Monthly Mode",
                "name": "monthly_mode",
                "type": "select",
                "default": monthly_mode,
                "options": [
                    {"text": "Day of Month (e.g. 15th)", "value": "day_of_month"},
                    {"text": "Weekday Position (e.g. First Monday)", "value": "weekday_position"},
                ],
                "help_text": "How to anchor the monthly recurrence.",
            },
        ]

        if monthly_mode == "day_of_month":
            elements.append({
                "display_name": "Day of Month",
                "name": "monthly_day",
                "type": "text",
                "subtype": "number",
                "default": current.get("monthly_day", "1"),
                "placeholder": "1–31",
                "help_text": "Day number (1–31). Clamped for short months.",
            })
        elif monthly_mode == "weekday_position":
            elements.append({
                "display_name": "Week",
                "name": "monthly_week",
                "type": "select",
                "default": current.get("monthly_week", "first"),
                "options": [
                    {"text": "First", "value": "first"},
                    {"text": "Second", "value": "second"},
                    {"text": "Third", "value": "third"},
                    {"text": "Fourth", "value": "fourth"},
                    {"text": "Last", "value": "last"},
                ],
                "help_text": "Which occurrence in the month.",
            })
            elements.append({
                "display_name": "Weekday",
                "name": "monthly_weekday",
                "type": "select",
                "default": current.get("monthly_weekday", "monday"),
                "options": [
                    {"text": "Monday", "value": "monday"},
                    {"text": "Tuesday", "value": "tuesday"},
                    {"text": "Wednesday", "value": "wednesday"},
                    {"text": "Thursday", "value": "thursday"},
                    {"text": "Friday", "value": "friday"},
                    {"text": "Saturday", "value": "saturday"},
                    {"text": "Sunday", "value": "sunday"},
                ],
                "help_text": "Which weekday.",
            })

        return elements

    @staticmethod
    def _yearly_elements(current: dict) -> list[dict]:
        """Fields for yearly recurrence."""
        return [
            {
                "display_name": "Month",
                "name": "yearly_month",
                "type": "select",
                "default": current.get("yearly_month", "1"),
                "options": [
                    {"text": "January", "value": "1"},
                    {"text": "February", "value": "2"},
                    {"text": "March", "value": "3"},
                    {"text": "April", "value": "4"},
                    {"text": "May", "value": "5"},
                    {"text": "June", "value": "6"},
                    {"text": "July", "value": "7"},
                    {"text": "August", "value": "8"},
                    {"text": "September", "value": "9"},
                    {"text": "October", "value": "10"},
                    {"text": "November", "value": "11"},
                    {"text": "December", "value": "12"},
                ],
                "help_text": "Month for the yearly recurrence.",
            },
            {
                "display_name": "Day",
                "name": "yearly_day",
                "type": "text",
                "subtype": "number",
                "default": current.get("yearly_day", "1"),
                "placeholder": "1–31",
                "help_text": "Day of the month.",
            },
        ]

    @staticmethod
    def _end_condition_elements(current: dict) -> list[dict]:
        """End-condition fields shown for all recurring types."""
        end_type = current.get("repeat_end_type", "forever")
        elements: list[dict] = [
            {
                "display_name": "Repeat Until",
                "name": "repeat_end_type",
                "type": "select",
                "default": end_type,
                "options": [
                    {"text": "Forever", "value": "forever"},
                    {"text": "End On Date", "value": "end_date"},
                    {"text": "End After N Occurrences", "value": "end_after"},
                ],
                "help_text": "When should the recurrence stop?",
            },
        ]

        if end_type == "end_date":
            elements.append({
                "display_name": "End Date",
                "name": "repeat_end_date",
                "type": "text",
                "default": current.get("repeat_end_date", ""),
                "placeholder": "YYYY-MM-DD",
                "help_text": "Recurrence stops after this date.",
            })
        elif end_type == "end_after":
            elements.append({
                "display_name": "Number of Occurrences",
                "name": "repeat_end_after",
                "type": "text",
                "subtype": "number",
                "default": current.get("repeat_end_after", "10"),
                "placeholder": "e.g. 20",
                "help_text": "Stop after this many executions.",
            })

        return elements

    def post_open_dialog(self, dialog_request: dict) -> None:
        """Send the dialog open request to the Mattermost API."""
        self._post("/actions/dialogs/open", json=dialog_request)
        logger.info("Opened interactive dialog (trigger_id=%s)", dialog_request.get("trigger_id"))

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def send_channel_message(self, channel_id: str, message: str) -> dict:
        """Post a message to a Mattermost channel."""
        logger.info("Sending message to channel %s (length=%d).", channel_id, len(message))
        payload = {
            "channel_id": channel_id,
            "message": message,
        }
        resp = self._post("/posts", json=payload)
        logger.info("Message sent to channel %s.", channel_id)
        return resp.json()

    def send_reminder_channel_message(self, message: str) -> dict:
        """Post a message to the configured reminder channel."""
        logger.info("Sending message to reminder channel (%s).", self.channel_id)
        return self.send_channel_message(self.channel_id, message)

    def send_ephemeral_post(self, channel_id: str, user_id: str, message: str) -> dict:
        """Send an ephemeral post visible only to a specific user."""
        payload = {
            "user_id": user_id,
            "post": {
                "channel_id": channel_id,
                "message": message,
            },
        }
        resp = self._post("/posts/ephemeral", json=payload)
        return resp.json()
