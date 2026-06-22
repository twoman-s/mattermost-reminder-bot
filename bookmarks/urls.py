"""
URL configuration for the bookmarks app.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from bookmarks.views import (
    BookmarkDialogSubmitView,
    BookmarkViewSet,
    DMWebhookView,
    SlashListbView,
)

# DRF router for bookmark API
router = DefaultRouter()
router.register(r"bookmarks", BookmarkViewSet, basename="bookmark")

urlpatterns = [
    # REST API
    path("api/v1/", include(router.urls)),
    # Mattermost webhooks
    path("mattermost/hooks/dm/", DMWebhookView.as_view(), name="mattermost-dm-webhook"),
    path("mattermost/slash/listb/", SlashListbView.as_view(), name="mattermost-slash-listb"),
    path(
        "mattermost/bookmark/dialog/submit/",
        BookmarkDialogSubmitView.as_view(),
        name="mattermost-bookmark-dialog-submit",
    ),
]
