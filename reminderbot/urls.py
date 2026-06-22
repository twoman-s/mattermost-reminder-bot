"""
ReminderBot URL Configuration.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("may/admin/", admin.site.urls),
    # API documentation
    path("may/api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("may/api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # Application URLs
    path("may/", include("reminders.urls")),
    path("may/", include("bookmarks.urls")),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

