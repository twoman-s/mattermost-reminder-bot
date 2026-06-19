"""
ReminderBot URL Configuration.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("nudgy/admin/", admin.site.urls),
    # API documentation
    path("nudgy/api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("nudgy/api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # Application URLs
    path("nudgy/", include("reminders.urls")),
]
