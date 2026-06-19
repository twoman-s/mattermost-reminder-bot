"""
URL configuration for the reminders app.

Note: Explicit paths (pending/, trigger/) are placed BEFORE the router
includes so they take precedence over the router's catch-all pattern.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from reminders.views import (
    DialogSubmitView,
    PendingRemindersView,
    ReminderViewSet,
    SlashRemindView,
    TriggerReminderView,
)

# DRF router for CRUD
router = DefaultRouter()
router.register(r"reminders", ReminderViewSet, basename="reminder")

urlpatterns = [
    # n8n integration endpoints — must come BEFORE the router
    path("nudgy/api/v1/reminders/pending/", PendingRemindersView.as_view(), name="reminders-pending"),
    path(
        "nudgy/api/v1/reminders/<uuid:external_id>/trigger/",
        TriggerReminderView.as_view(),
        name="reminders-trigger",
    ),
    # REST API — CRUD (router)
    path("nudgy/api/v1/", include(router.urls)),
    # Mattermost webhooks
    path("nudgy/mattermost/slash/remind/", SlashRemindView.as_view(), name="mattermost-slash-remind"),
    path("nudgy/mattermost/dialog/submit/", DialogSubmitView.as_view(), name="mattermost-dialog-submit"),
]
