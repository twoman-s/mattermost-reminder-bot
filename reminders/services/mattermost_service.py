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
        resp = requests.get(url, headers=self._headers, timeout=10, **kwargs)
        resp.raise_for_status()
        return resp

    def _post(self, path: str, json: dict | None = None, **kwargs: Any) -> requests.Response:
        url = self._api(path)
        resp = requests.post(url, headers=self._headers, json=json, timeout=10, **kwargs)
        resp.raise_for_status()
        return resp

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

    def open_reminder_dialog(self, trigger_id: str) -> dict:
        """
        Open the 'Create Reminder' interactive dialog in Mattermost.

        :param trigger_id: The trigger_id provided by Mattermost when the
                           slash command is invoked. Required by the Dialogs API.
        """
        dialog_request = {
            "trigger_id": trigger_id,
            "url": "",  # Will be set by the view before calling
            "dialog": {
                "callback_id": "create_reminder",
                "title": "Create Reminder",
                "submit_label": "Save",
                "elements": [
                    {
                        "display_name": "Reminder Title",
                        "name": "title",
                        "type": "text",
                        "placeholder": "e.g. Pay Electricity Bill",
                        "help_text": "Short title for your reminder.",
                    },
                    {
                        "display_name": "Description",
                        "name": "description",
                        "type": "textarea",
                        "optional": True,
                        "placeholder": "Optional details…",
                        "help_text": "Additional notes for the reminder.",
                    },
                    {
                        "display_name": "Reminder Date",
                        "name": "reminder_date",
                        "type": "text",
                        "placeholder": "YYYY-MM-DD",
                        "help_text": "Date for the reminder (e.g. 2026-06-20).",
                    },
                    {
                        "display_name": "Reminder Time",
                        "name": "reminder_time",
                        "type": "text",
                        "placeholder": "HH:MM (24-hour)",
                        "help_text": "Time in 24-hour format (e.g. 14:30).",
                    },
                    {
                        "display_name": "Repeat Type",
                        "name": "repeat_type",
                        "type": "select",
                        "default": "none",
                        "options": [
                            {"text": "Never", "value": "none"},
                            {"text": "Hourly", "value": "hourly"},
                            {"text": "Daily", "value": "daily"},
                            {"text": "Weekly", "value": "weekly"},
                            {"text": "Monthly", "value": "monthly"},
                            {"text": "Yearly", "value": "yearly"},
                        ],
                        "help_text": "How often should this reminder repeat?",
                    },
                    {
                        "display_name": "Snooze Minutes",
                        "name": "snooze_minutes",
                        "type": "select",
                        "default": "0",
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
                    },
                ],
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
        payload = {
            "channel_id": channel_id,
            "message": message,
        }
        resp = self._post("/posts", json=payload)
        return resp.json()

    def send_reminder_channel_message(self, message: str) -> dict:
        """Post a message to the configured reminder channel."""
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
