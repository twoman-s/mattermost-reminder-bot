"""
Unit tests for Reminder models and services.
"""

from datetime import date, datetime
from django.test import TestCase
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
