"""
URL configuration for the reminders app.

Note: Explicit paths (pending/, trigger/) are placed BEFORE the router
includes so they take precedence over the router's catch-all pattern.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from reminders.views import (
    DialogRefreshView,
    DialogSubmitView,
    ReminderViewSet,
    SlashListrView,
    SlashRemindView,
)

# DRF router for CRUD
router = DefaultRouter()
router.register(r"reminders", ReminderViewSet, basename="reminder")

urlpatterns = [
    # REST API — CRUD (router)
    path("api/v1/", include(router.urls)),
    # Mattermost webhooks
    path("mattermost/slash/remind/", SlashRemindView.as_view(), name="mattermost-slash-remind"),
    path("mattermost/slash/listr/", SlashListrView.as_view(), name="mattermost-slash-listr"),
    path("mattermost/dialog/submit/", DialogSubmitView.as_view(), name="mattermost-dialog-submit"),
    path("mattermost/dialog/refresh/", DialogRefreshView.as_view(), name="mattermost-dialog-refresh"),
]
