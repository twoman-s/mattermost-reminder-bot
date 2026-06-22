"""
Django settings for ReminderBot project.

Mattermost reminder management backend with Interactive Dialog support.
"""

import os
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Environment configuration
env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, "django-insecure-change-me"),
    MATTERMOST_URL=(str, ""),
    MATTERMOST_BOT_TOKEN=(str, ""),
    MATTERMOST_REMINDER_CHANNEL_ID=(str, ""),
    MATTERMOST_BOOKMARKS_CHANNEL_ID=(str, ""),
)

# Read .env file
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env("DEBUG")

ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "drf_spectacular",
    # Local
    "reminders",
    "bookmarks",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Custom
    "reminderbot.middleware.RequestLoggingMiddleware",
]

ROOT_URLCONF = "reminderbot.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "reminderbot.wsgi.application"

# Database — SQLite stored in ./data/ for Docker volume persistence
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media files (bookmark assets, images)
MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# drf-spectacular
SPECTACULAR_SETTINGS = {
    "TITLE": "ReminderBot API",
    "DESCRIPTION": "Mattermost reminder management backend API. "
    "Provides CRUD operations for reminders, Mattermost Interactive Dialog handling, "
    "and endpoints for n8n integration.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v[0-9]",
    "TAGS": [
        {"name": "Reminders", "description": "CRUD operations for reminders"},
        {"name": "n8n Integration", "description": "Endpoints consumed by n8n workflows"},
        {"name": "Mattermost", "description": "Mattermost slash commands and dialog handling"},
    ],
}

# Mattermost Configuration
MATTERMOST_URL = env("MATTERMOST_URL").rstrip("/")
MATTERMOST_BOT_TOKEN = env("MATTERMOST_BOT_TOKEN")
MATTERMOST_REMINDER_CHANNEL_ID = env("MATTERMOST_REMINDER_CHANNEL_ID")
MATTERMOST_BOOKMARKS_CHANNEL_ID = env("MATTERMOST_BOOKMARKS_CHANNEL_ID")

# CSRF exemption for Mattermost webhook endpoints
CSRF_TRUSTED_ORIGINS = [MATTERMOST_URL] if MATTERMOST_URL else []

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} [{levelname}] {name} | {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "format": "[{levelname}] {name} | {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "level": "DEBUG",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "reminderbot.log",
            "maxBytes": 5 * 1024 * 1024,  # 5 MB
            "backupCount": 5,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "loggers": {
        # Root logger — catches everything not matched below
        "": {
            "handlers": ["console", "file"],
            "level": "WARNING",
        },
        # Django internals
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file"],
            "level": "ERROR",
            "propagate": False,
        },
        # Request/response middleware
        "reminderbot.middleware": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        # Application loggers
        "reminders": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
        "bookmarks": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
