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
      - Open interactive dialogs
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

    def build_dialog_elements(self, submission: dict) -> list[dict]:
        """Dynamically build dialog elements based on the current submission values."""
        elements = [
            {
                "display_name": "Reminder Title",
                "name": "title",
                "type": "text",
                "placeholder": "e.g. Pay Electricity Bill",
                "help_text": "Short title for your reminder.",
                "default": submission.get("title") or "",
            },
            {
                "display_name": "Description",
                "name": "description",
                "type": "textarea",
                "optional": True,
                "placeholder": "Optional details…",
                "help_text": "Additional notes for the reminder.",
                "default": submission.get("description") or "",
            },
            {
                "display_name": "Reminder Time",
                "name": "reminder_datetime",
                "type": "datetime",
                "help_text": "When should this reminder trigger?",
                "default": submission.get("reminder_datetime") or "",
                "datetime_config": {
                    "min_date": "today",
                    "time_interval": 15
                }
            },
            {
                "display_name": "Recurrence Type",
                "name": "repeat_type",
                "type": "select",
                "default": submission.get("repeat_type") or "none",
                "refresh": True,
                "options": [
                    {"text": "One Time", "value": "none"},
                    {"text": "Interval", "value": "interval"},
                    {"text": "Weekly", "value": "weekly"},
                    {"text": "Monthly", "value": "monthly"},
                    {"text": "Yearly", "value": "yearly"},
                ],
            }
        ]

        repeat_type = submission.get("repeat_type") or "none"

        if repeat_type == "interval":
            elements.extend([
                {
                    "display_name": "Interval Value",
                    "name": "repeat_interval",
                    "type": "text",
                    "default": submission.get("repeat_interval") or "1",
                    "help_text": "e.g. 2",
                },
                {
                    "display_name": "Interval Unit",
                    "name": "repeat_unit",
                    "type": "select",
                    "default": submission.get("repeat_unit") or "day",
                    "options": [
                        {"text": "Minutes", "value": "minute"},
                        {"text": "Hours", "value": "hour"},
                        {"text": "Days", "value": "day"},
                        {"text": "Weeks", "value": "week"},
                        {"text": "Months", "value": "month"},
                        {"text": "Years", "value": "year"},
                    ],
                }
            ])

        elif repeat_type == "weekly":
            elements.append({
                "display_name": "Weekdays",
                "name": "repeat_weekdays",
                "type": "select",
                "multiselect": True,
                "default": submission.get("repeat_weekdays") or "",
                "options": [
                    {"text": "Monday", "value": "monday"},
                    {"text": "Tuesday", "value": "tuesday"},
                    {"text": "Wednesday", "value": "wednesday"},
                    {"text": "Thursday", "value": "thursday"},
                    {"text": "Friday", "value": "friday"},
                    {"text": "Saturday", "value": "saturday"},
                    {"text": "Sunday", "value": "sunday"},
                ],
            })

        elif repeat_type == "monthly":
            monthly_mode = submission.get("monthly_mode") or "day_of_month"
            elements.append({
                "display_name": "Monthly Mode",
                "name": "monthly_mode",
                "type": "select",
                "default": monthly_mode,
                "refresh": True,
                "options": [
                    {"text": "Day Of Month", "value": "day_of_month"},
                    {"text": "Weekday Position", "value": "weekday_position"},
                ],
            })

            if monthly_mode == "day_of_month":
                elements.append({
                    "display_name": "Day Number",
                    "name": "monthly_day",
                    "type": "text",
                    "default": submission.get("monthly_day") or "15",
                    "help_text": "Day of the month to trigger (1-31).",
                })
            elif monthly_mode == "weekday_position":
                elements.extend([
                    {
                        "display_name": "Week Selector",
                        "name": "monthly_week",
                        "type": "select",
                        "default": submission.get("monthly_week") or "first",
                        "options": [
                            {"text": "First", "value": "first"},
                            {"text": "Second", "value": "second"},
                            {"text": "Third", "value": "third"},
                            {"text": "Fourth", "value": "fourth"},
                            {"text": "Last", "value": "last"},
                        ],
                    },
                    {
                        "display_name": "Weekday Selector",
                        "name": "monthly_weekday",
                        "type": "select",
                        "default": submission.get("monthly_weekday") or "monday",
                        "options": [
                            {"text": "Monday", "value": "monday"},
                            {"text": "Tuesday", "value": "tuesday"},
                            {"text": "Wednesday", "value": "wednesday"},
                            {"text": "Thursday", "value": "thursday"},
                            {"text": "Friday", "value": "friday"},
                            {"text": "Saturday", "value": "saturday"},
                            {"text": "Sunday", "value": "sunday"},
                        ],
                    }
                ])

        elif repeat_type == "yearly":
            elements.extend([
                {
                    "display_name": "Month",
                    "name": "yearly_month",
                    "type": "select",
                    "default": submission.get("yearly_month") or "1",
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
                },
                {
                    "display_name": "Day",
                    "name": "yearly_day",
                    "type": "text",
                    "default": submission.get("yearly_day") or "1",
                    "help_text": "Day of the month to trigger (1-31).",
                }
            ])

        # If recurrence is active, show end condition fields
        if repeat_type != "none":
            repeat_until = submission.get("repeat_until") or "forever"
            elements.append({
                "display_name": "Repeat Until",
                "name": "repeat_until",
                "type": "select",
                "default": repeat_until,
                "refresh": True,
                "options": [
                    {"text": "Forever", "value": "forever"},
                    {"text": "End On Date", "value": "end_date"},
                    {"text": "End After Occurrences", "value": "end_after"},
                ],
            })

            if repeat_until == "end_date":
                elements.append({
                    "display_name": "End Date",
                    "name": "repeat_end_date",
                    "type": "date",
                    "default": submission.get("repeat_end_date") or "",
                    "help_text": "Stop repeating after this date.",
                })
            elif repeat_until == "end_after":
                elements.append({
                    "display_name": "Occurrence Count",
                    "name": "repeat_end_after",
                    "type": "text",
                    "default": submission.get("repeat_end_after") or "10",
                    "help_text": "Number of executions before stopping.",
                })

        return elements

    def open_reminder_dialog(
        self,
        trigger_id: str,
        callback_url: str,
        refresh_url: str,
        submission: dict | None = None
    ) -> dict:
        """
        Build the payload to open the interactive dialog in Mattermost.
        """
        if submission is None:
            submission = {}

        dialog_request = {
            "trigger_id": trigger_id,
            "url": callback_url,
            "dialog": {
                "callback_id": "create_reminder",
                "title": "Create Reminder",
                "submit_label": "Save",
                "source_url": refresh_url,
                "elements": self.build_dialog_elements(submission),
            },
        }
        return dialog_request

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
