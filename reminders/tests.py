"""
Unit tests for Reminder models and services.
"""

from datetime import date, datetime
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from reminders.models import Reminder, RepeatType, ReminderStatus
from reminders.services.reminder_service import RecurrenceService, ReminderExecutionService


class RecurrenceServiceTests(TestCase):
    """Test suite for RecurrenceService recurrence calculations."""

    def setUp(self) -> None:
        # Standard mock timezone setup (e.g. UTC)
        self.tz = timezone.get_current_timezone()

    def test_no_recurrence(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        reminder = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.NONE,
        )
        self.assertIsNone(RecurrenceService.calculate_next_occurrence(reminder))

    def test_interval_minutes(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        reminder = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.INTERVAL,
            repeat_interval=15,
            repeat_unit="minute",
        )
        # We need to simulate the 'now' state.
        # RecurrenceService.calculate_next_occurrence loops until next_dt > now.
        # Let's ensure now is set so it triggers the calculation.
        next_dt = RecurrenceService.calculate_next_occurrence(reminder)
        self.assertEqual(next_dt, dt + timezone.timedelta(minutes=15))

    def test_interval_hours(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        reminder = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.INTERVAL,
            repeat_interval=3,
            repeat_unit="hour",
        )
        next_dt = RecurrenceService.calculate_next_occurrence(reminder)
        self.assertEqual(next_dt, dt + timezone.timedelta(hours=3))

    def test_interval_days(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        reminder = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.INTERVAL,
            repeat_interval=5,
            repeat_unit="day",
        )
        next_dt = RecurrenceService.calculate_next_occurrence(reminder)
        self.assertEqual(next_dt, dt + timezone.timedelta(days=5))

    def test_weekly_weekdays(self) -> None:
        # 2026-06-19 is Friday (weekday = 4)
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        
        # Next Monday (2026-06-22) and Friday (2026-06-26)
        reminder = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.WEEKLY,
            repeat_interval=1,
            repeat_weekdays=["monday", "friday"],
        )
        next_dt = RecurrenceService.calculate_next_occurrence(reminder)
        # From Friday 2026-06-19, next in list should be Monday 2026-06-22
        self.assertEqual(next_dt.date(), date(2026, 6, 22))
        self.assertEqual(next_dt.time(), dt.time())

        # Test weekly with larger interval (every 2 weeks, Monday and Friday)
        # From Friday (2026-06-19), next occurrence wrap-around (Monday) should skip 1 week and land on 2026-06-29 (Monday of week 3)
        reminder_interval = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.WEEKLY,
            repeat_interval=2,
            repeat_weekdays=["monday", "friday"],
        )
        next_dt_interval = RecurrenceService.calculate_next_occurrence(reminder_interval)
        self.assertEqual(next_dt_interval.date(), date(2026, 6, 29))

    def test_monthly_day_of_month(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        reminder = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.MONTHLY,
            repeat_interval=1,
            monthly_mode="day_of_month",
            monthly_day=15,
        )
        next_dt = RecurrenceService.calculate_next_occurrence(reminder)
        self.assertEqual(next_dt.date(), date(2026, 7, 15))

        # Test clipping at end of month (e.g. Oct 31st repeat, next month has 30 days)
        dt_oct = timezone.make_aware(datetime(2026, 10, 31, 12, 0), self.tz)
        reminder_oct = Reminder(
            reminder_datetime=dt_oct,
            repeat_type=RepeatType.MONTHLY,
            repeat_interval=1,
            monthly_mode="day_of_month",
            monthly_day=31,
        )
        next_dt_oct = RecurrenceService.calculate_next_occurrence(reminder_oct)
        self.assertEqual(next_dt_oct.date(), date(2026, 11, 30))  # November has 30 days

    def test_monthly_weekday_position(self) -> None:
        # First Friday of June 2026 was June 5th.
        # Let's say scheduled is First Friday of July 2026.
        # July 1st is Wednesday, July 2nd is Thursday, July 3rd is Friday (First Friday).
        dt = timezone.make_aware(datetime(2026, 6, 5, 12, 0), self.tz)
        reminder = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.MONTHLY,
            repeat_interval=1,
            monthly_mode="weekday_position",
            monthly_week="first",
            monthly_weekday="friday",
        )
        next_dt = RecurrenceService.calculate_next_occurrence(reminder)
        self.assertEqual(next_dt.date(), date(2026, 7, 3))

    def test_yearly_recurrence(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        reminder = Reminder(
            reminder_datetime=dt,
            repeat_type=RepeatType.YEARLY,
            repeat_interval=1,
            yearly_month=6,
            yearly_day=25,
        )
        next_dt = RecurrenceService.calculate_next_occurrence(reminder)
        self.assertEqual(next_dt.date(), date(2027, 6, 25))


class ReminderExecutionServiceTests(TestCase):
    """Test suite for ReminderExecutionService trigger logic and limits."""

    def setUp(self) -> None:
        self.tz = timezone.get_current_timezone()

    def test_trigger_one_off(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        reminder = Reminder.objects.create(
            title="One Off",
            reminder_datetime=dt,
            repeat_type=RepeatType.NONE,
            status=ReminderStatus.PENDING,
        )
        
        # Mock MM service so it doesn't try to send external HTTP calls
        class MockMM:
            def send_reminder_channel_message(self, message: str) -> None:
                pass

        service = ReminderExecutionService(mattermost_service=MockMM())
        updated_reminder = service.trigger_reminder(reminder)

        self.assertEqual(updated_reminder.status, ReminderStatus.COMPLETED)
        self.assertEqual(updated_reminder.occurrence_count, 1)
        self.assertIsNotNone(updated_reminder.completed_at)

    def test_trigger_limit_occurrences(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        # End after 2 occurrences
        reminder = Reminder.objects.create(
            title="Recurring Limit",
            reminder_datetime=dt,
            repeat_type=RepeatType.INTERVAL,
            repeat_interval=1,
            repeat_unit="day",
            repeat_forever=False,
            repeat_end_after=2,
            occurrence_count=1,  # Already triggered once
            status=ReminderStatus.PENDING,
        )

        class MockMM:
            def send_reminder_channel_message(self, message: str) -> None:
                pass

        service = ReminderExecutionService(mattermost_service=MockMM())
        updated_reminder = service.trigger_reminder(reminder)

        self.assertEqual(updated_reminder.status, ReminderStatus.COMPLETED)
        self.assertEqual(updated_reminder.occurrence_count, 2)
        self.assertIsNotNone(updated_reminder.completed_at)

    def test_trigger_limit_end_date(self) -> None:
        dt = timezone.make_aware(datetime(2026, 6, 19, 12, 0), self.tz)
        # Repeat daily, but stop by end of day 2026-06-20
        reminder = Reminder.objects.create(
            title="Recurring Limit Date",
            reminder_datetime=dt,
            repeat_type=RepeatType.INTERVAL,
            repeat_interval=1,
            repeat_unit="day",
            repeat_forever=False,
            repeat_end_date=date(2026, 6, 20),
            status=ReminderStatus.PENDING,
        )

        class MockMM:
            def send_reminder_channel_message(self, message: str) -> None:
                pass

        service = ReminderExecutionService(mattermost_service=MockMM())
        
        # First execution -> occurrence_count becomes 1, next_dt becomes 2026-06-20 (<= end_date)
        updated = service.trigger_reminder(reminder)
        self.assertEqual(updated.status, ReminderStatus.PENDING)
        self.assertEqual(updated.reminder_datetime.date(), date(2026, 6, 20))

        # Second execution -> occurrence_count becomes 2, next_dt becomes 2026-06-21 (> end_date)
        updated = service.trigger_reminder(updated)
        self.assertEqual(updated.status, ReminderStatus.COMPLETED)
        self.assertIsNotNone(updated.completed_at)


from rest_framework.test import APITestCase

class SlashListrViewTests(APITestCase):
    """Test suite for /listr slash command endpoint and interactive dialog flows."""

    def setUp(self) -> None:
        self.tz = timezone.get_current_timezone()
        # Create a couple of reminders
        self.r1 = Reminder.objects.create(
            title="Rem 1",
            reminder_datetime=timezone.make_aware(datetime(2026, 6, 20, 10, 0), self.tz),
            repeat_type=RepeatType.NONE,
        )
        self.r2 = Reminder.objects.create(
            title="Rem 2",
            reminder_datetime=timezone.make_aware(datetime(2026, 6, 21, 10, 0), self.tz),
            repeat_type=RepeatType.NONE,
        )

    def test_listr_get_paginated(self) -> None:
        url = reverse("mattermost-slash-listr")
        resp = self.client.get(url, {"page": 1, "page_size": 1})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 2)
        self.assertEqual(resp.data["num_pages"], 2)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["title"], "Rem 1")

    def test_listr_post_slash_command(self) -> None:
        url = reverse("mattermost-slash-listr")
        # Mock MM post open dialog to prevent actual post calls
        from unittest.mock import patch
        with patch("reminders.services.MattermostService.post_open_dialog") as mock_open:
            resp = self.client.post(url, {
                "trigger_id": "test_trig_id",
                "user_id": "user_id_123",
                "channel_id": "channel_id_456"
            })
            self.assertEqual(resp.status_code, 200)
            mock_open.assert_called_once()

    def test_dialog_refresh_list(self) -> None:
        url = reverse("mattermost-dialog-refresh")
        resp = self.client.post(url, {
            "callback_id": "list_reminders",
            "submission": {
                "page": "1",
                "page_size": "1",
                "pagination_action": "next"
            }
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "form")
        # Because we moved next, page should be updated to 2
        elements = resp.data["form"]["elements"]
        page_elem = next(el for el in elements if el["name"] == "page")
        self.assertEqual(page_elem["default"], "2")

    def test_dialog_submit_edit_chained_form(self) -> None:
        url = reverse("mattermost-dialog-submit")
        # Submit the list dialog selecting r1 to edit
        resp = self.client.post(url, {
            "callback_id": "list_reminders",
            "submission": {
                "reminder_to_edit": str(self.r1.external_id)
            }
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["type"], "form")
        self.assertEqual(resp.data["form"]["callback_id"], f"edit_reminder_{self.r1.external_id}")
        self.assertEqual(resp.data["form"]["submit_label"], "Save Changes")

    def test_dialog_submit_save_edit(self) -> None:
        url = reverse("mattermost-dialog-submit")
        # Save updates to r1
        new_dt = timezone.make_aware(datetime(2026, 6, 25, 12, 0), self.tz)
        resp = self.client.post(url, {
            "callback_id": f"edit_reminder_{self.r1.external_id}",
            "submission": {
                "title": "Rem 1 Updated",
                "reminder_datetime": new_dt.isoformat(),
                "repeat_type": "none",
            }
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        
        # Check if DB was updated
        self.r1.refresh_from_db()
        self.assertEqual(self.r1.title, "Rem 1 Updated")
        self.assertEqual(self.r1.reminder_datetime, new_dt)

