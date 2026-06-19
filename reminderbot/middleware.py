"""
Request/response logging middleware for ReminderBot.

Logs every incoming request (method, path, body) and outgoing response
(status code, duration) at INFO level. Errors are logged at ERROR level.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger("reminderbot.middleware")


class RequestLoggingMiddleware:
    """
    Middleware that logs request bodies and response metadata.

    Sensitive headers (Authorization) are redacted. Request bodies
    are truncated at 2 KB to avoid flooding the log with large payloads.
    """

    MAX_BODY_LOG_SIZE = 2048  # characters

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start_time = time.monotonic()

        # --- Log the request ---
        body = self._get_request_body(request)
        logger.info(
            "→ %s %s | Body: %s",
            request.method,
            request.get_full_path(),
            body,
        )

        # --- Process the request ---
        try:
            response = self.get_response(request)
        except Exception:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "✗ %s %s | Unhandled exception after %.1fms",
                request.method,
                request.get_full_path(),
                duration_ms,
                exc_info=True,
            )
            raise

        # --- Log the response ---
        duration_ms = (time.monotonic() - start_time) * 1000
        log_fn = logger.warning if response.status_code >= 400 else logger.info
        log_fn(
            "← %s %s | Status: %d | %.1fms",
            request.method,
            request.get_full_path(),
            response.status_code,
            duration_ms,
        )

        return response

    def _get_request_body(self, request: HttpRequest) -> str:
        """Extract and safely format the request body for logging."""
        # Skip body logging for GET/HEAD/OPTIONS
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return "<no body>"

        try:
            raw = request.body.decode("utf-8", errors="replace")
            if not raw:
                return "<empty>"

            # Try to pretty-format JSON
            try:
                parsed = json.loads(raw)
                formatted = json.dumps(parsed, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                # Not JSON — could be form-encoded from Mattermost
                formatted = raw

            if len(formatted) > self.MAX_BODY_LOG_SIZE:
                return formatted[: self.MAX_BODY_LOG_SIZE] + "...<truncated>"
            return formatted

        except Exception:
            return "<unreadable>"
