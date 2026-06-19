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

from reminders.models import Reminder

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

    def build_list_dialog(self, submission: dict) -> dict:
        """
        Build the list dialog with pagination and edit selection.
        """
        page_num = 1
        try:
            page_num = int(submission.get("page") or 1)
        except ValueError:
            pass

        page_size = 15
        try:
            page_size = int(submission.get("page_size") or 15)
        except ValueError:
            pass

        pagination_action = submission.get("pagination_action") or "current"
        if pagination_action == "prev":
            page_num = max(1, page_num - 1)
        elif pagination_action == "next":
            page_num = page_num + 1

        reminders_qs = Reminder.objects.all().order_by("reminder_datetime")
        total_count = reminders_qs.count()

        from django.core.paginator import Paginator
        paginator = Paginator(reminders_qs, page_size)

        if page_num > paginator.num_pages:
            page_num = paginator.num_pages
        if page_num < 1:
            page_num = 1

        page_obj = paginator.get_page(page_num) if total_count > 0 else []

        # Build table
        if total_count > 0:
            table_lines = [
                "### Reminders List",
                "",
                "| Title | When | Repeats | Next Run | Status |",
                "| :--- | :--- | :--- | :--- | :--- |"
            ]
            for r in page_obj:
                when_str = r.reminder_datetime.strftime("%Y-%m-%d %H:%M")
                repeats_str = r.get_repeat_type_display()
                next_run_str = r.next_run_at.strftime("%Y-%m-%d %H:%M") if r.next_run_at else ""
                status_str = r.get_status_display()
                title_escaped = r.title.replace("|", "\\|")
                table_lines.append(f"| {title_escaped} | {when_str} | {repeats_str} | {next_run_str} | {status_str} |")
            markdown_table = "\n".join(table_lines)
        else:
            markdown_table = "### Reminders List\n\nNo reminders found."

        # Page options
        page_options = []
        num_pages = paginator.num_pages if total_count > 0 else 1
        for p in range(1, num_pages + 1):
            page_options.append({"text": f"Page {p}", "value": str(p)})

        # Page size options (5 to 50, step 5)
        page_size_options = []
        for sz in range(5, 51, 5):
            page_size_options.append({"text": f"{sz} items", "value": str(sz)})

        # Reminder options to edit
        edit_options = []
        if total_count > 0:
            for r in page_obj:
                edit_options.append({"text": r.title[:30], "value": str(r.external_id)})
        else:
            edit_options.append({"text": "No reminders to edit", "value": "none"})

        elements = [
            {
                "display_name": "Page Size",
                "name": "page_size",
                "type": "select",
                "default": str(page_size),
                "refresh": True,
                "options": page_size_options,
            },
            {
                "display_name": "Select Page",
                "name": "page",
                "type": "select",
                "default": str(page_num),
                "refresh": True,
                "options": page_options,
            },
            {
                "display_name": "Pagination Actions",
                "name": "pagination_action",
                "type": "select",
                "default": "current",
                "refresh": True,
                "options": [
                    {"text": "Stay on Current Page", "value": "current"},
                    {"text": "◄ Previous Page", "value": "prev"},
                    {"text": "Next Page ►", "value": "next"},
                ],
            }
        ]

        if total_count > 0:
            elements.append({
                "display_name": "Select Reminder to Edit",
                "name": "reminder_to_edit",
                "type": "select",
                "default": submission.get("reminder_to_edit") or "",
                "options": edit_options,
                "optional": True,
                "help_text": "Select a reminder and click Edit below.",
            })

        dialog = {
            "callback_id": "list_reminders",
            "title": f"Manage Reminders ({total_count} total)",
            "submit_label": "Edit",
            "introduction_text": markdown_table,
            "elements": elements,
        }
        return dialog

    def build_edit_dialog(self, reminder: Reminder, submission: dict | None = None) -> dict:
        """
        Build the edit dialog for a specific reminder.
        """
        if submission is None:
            end_date_str = ""
            if reminder.repeat_end_date:
                end_date_str = reminder.repeat_end_date.strftime("%Y-%m-%d")

            repeat_until = "forever"
            if not reminder.repeat_forever:
                if reminder.repeat_end_date:
                    repeat_until = "end_date"
                elif reminder.repeat_end_after:
                    repeat_until = "end_after"

            submission = {
                "title": reminder.title,
                "description": reminder.description,
                "reminder_datetime": reminder.reminder_datetime.isoformat(),
                "repeat_type": reminder.repeat_type,
                "repeat_interval": str(reminder.repeat_interval),
                "repeat_unit": reminder.repeat_unit,
                "repeat_weekdays": ",".join(reminder.repeat_weekdays),
                "monthly_mode": reminder.monthly_mode,
                "monthly_day": str(reminder.monthly_day or 15),
                "monthly_week": reminder.monthly_week,
                "monthly_weekday": reminder.monthly_weekday,
                "yearly_month": str(reminder.yearly_month or 1),
                "yearly_day": str(reminder.yearly_day or 1),
                "repeat_until": repeat_until,
                "repeat_end_date": end_date_str,
                "repeat_end_after": str(reminder.repeat_end_after or 10),
            }

        dialog = {
            "callback_id": f"edit_reminder_{reminder.external_id}",
            "title": "Edit Reminder",
            "submit_label": "Save Changes",
            "elements": self.build_dialog_elements(submission),
        }
        return dialog

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
