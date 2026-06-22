"""
Views for the Bookmark Vault module.

Groups:
  1. DM Webhook — receives Mattermost DMs, extracts URLs, creates bookmarks
  2. REST API — search, detail, export endpoints
  3. Mattermost Slash Commands — /listb interactive dialog
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from django.db import IntegrityError, transaction
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from bookmarks.models import Bookmark, BookmarkStatus, BookmarkType
from bookmarks.processor import process_bookmark_async
from bookmarks.serializers import (
    BookmarkDetailSerializer,
    BookmarkExportSerializer,
    BookmarkListSerializer,
)
from bookmarks.services.exporter import BookmarkExporterService
from bookmarks.services.search import BookmarkSearchService
from reminders.services.mattermost import MattermostService

logger = logging.getLogger(__name__)

# Regex for extracting URLs from message text
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'\)\]]+",
    re.IGNORECASE,
)


# ======================================================================
# DM Webhook View
# ======================================================================


class DMWebhookView(APIView):
    """
    POST /nudgy/mattermost/hooks/dm/

    Receives Mattermost Outgoing Webhook payloads from DM channels.
    Extracts URLs from the message text, creates bookmarks, and
    kicks off background processing.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Bookmarks"],
        summary="Handle DM webhook for bookmark saving",
        description="Extracts URLs from DM messages and creates bookmarks automatically.",
        responses={200: OpenApiResponse(description="Bookmark acknowledgement or empty 200.")},
    )
    def post(self, request: Request) -> Response:
        payload = request.data
        user_id = payload.get("user_id", "")
        channel_id = payload.get("channel_id", "")
        text = payload.get("text", "")

        # Mattermost sends channel_type for outgoing webhooks
        # We only process DMs (channel_type "D")
        # If channel_type is not present, we still try to process
        channel_type = payload.get("channel_type", "D")
        if channel_type != "D":
            logger.debug("Ignoring non-DM message (channel_type=%s)", channel_type)
            return Response(status=status.HTTP_200_OK)

        # Ignore bot's own messages (prevent loops)
        bot_id = payload.get("bot_user_id", "")
        if bot_id:
            return Response(status=status.HTTP_200_OK)

        logger.info(
            "DM webhook received — user: %s, channel: %s, text_length: %d",
            user_id,
            channel_id,
            len(text),
        )

        # Extract URLs
        urls = _URL_PATTERN.findall(text)
        if not urls:
            logger.debug("No URLs found in DM message.")
            return Response(status=status.HTTP_200_OK)

        # Deduplicate preserving order
        seen: set[str] = set()
        unique_urls: list[str] = []
        for u in urls:
            # Clean trailing punctuation that regex may capture
            u = u.rstrip(".,;:!?)")
            if u not in seen:
                seen.add(u)
                unique_urls.append(u)

        logger.info("Found %d unique URL(s) in DM: %s", len(unique_urls), unique_urls)

        created_bookmarks: list[Bookmark] = []
        duplicate_bookmarks: list[Bookmark] = []

        for url in unique_urls:
            domain = urlparse(url).netloc or ""

            try:
                with transaction.atomic():
                    bookmark = Bookmark.objects.create(
                        mattermost_user_id=user_id,
                        url=url,
                        domain=domain,
                        status=BookmarkStatus.PROCESSING,
                    )
                created_bookmarks.append(bookmark)
                logger.info("Created bookmark %s for URL %s", bookmark.external_id, url)

                # Fire background processor
                process_bookmark_async(bookmark.pk, channel_id)

            except IntegrityError:
                # Duplicate URL — fetch existing
                existing = Bookmark.objects.filter(url=url).first()
                if existing:
                    duplicate_bookmarks.append(existing)
                    logger.info("Duplicate URL %s — existing bookmark %s", url, existing.external_id)

        # Build immediate acknowledgement
        response_lines: list[str] = []

        if created_bookmarks:
            for bk in created_bookmarks:
                response_lines.append(
                    f"📚 **Bookmark Saved**\n\n"
                    f"**URL:** {bk.url}\n"
                    f"**Domain:** {bk.domain}\n\n"
                    f"_Processing metadata..._"
                )

        if duplicate_bookmarks:
            for bk in duplicate_bookmarks:
                response_lines.append(
                    f"🔄 **Already bookmarked**\n\n"
                    f"**Title:** {bk.title or bk.url}\n"
                    f"**Domain:** {bk.domain}\n"
                    f"**ID:** BK-{str(bk.external_id)[:8]}"
                )

        if response_lines:
            response_text = "\n\n---\n\n".join(response_lines)
            return Response({"text": response_text}, status=status.HTTP_200_OK)

        return Response(status=status.HTTP_200_OK)


# ======================================================================
# REST API ViewSet
# ======================================================================


class BookmarkViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Bookmark API — read-only with search, detail, and export.

    Bookmarks are created via DM webhooks, not through the API.
    """

    queryset = Bookmark.objects.all()
    lookup_field = "external_id"
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return BookmarkDetailSerializer
        return BookmarkListSerializer

    @extend_schema(
        tags=["Bookmarks"],
        summary="List / search bookmarks",
        parameters=[
            OpenApiParameter(name="search", type=str, description="Free text search"),
            OpenApiParameter(name="domain", type=str, description="Filter by domain"),
            OpenApiParameter(name="bookmark_type", type=str, description="Filter by type"),
            OpenApiParameter(name="tag", type=str, description="Filter by tag slug"),
            OpenApiParameter(name="collection", type=str, description="Filter by collection name"),
            OpenApiParameter(name="is_archived", type=bool, description="Filter by archived status"),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        filters = {
            "search": request.query_params.get("search", ""),
            "domain": request.query_params.get("domain", ""),
            "bookmark_type": request.query_params.get("bookmark_type", ""),
            "tag": request.query_params.get("tag", ""),
            "collection": request.query_params.get("collection", ""),
            "is_archived": request.query_params.get("is_archived"),
        }
        self.queryset = BookmarkSearchService.search(filters)
        return super().list(request, *args, **kwargs)

    @extend_schema(
        tags=["Bookmarks"],
        summary="Retrieve bookmark detail",
    )
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        return super().retrieve(request, *args, **kwargs)

    @extend_schema(
        tags=["Bookmarks"],
        summary="Export bookmarks as Markdown",
        responses={200: BookmarkExportSerializer(many=True)},
    )
    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request: Request) -> Response:
        """Export all bookmarks as Obsidian-compatible Markdown."""
        bookmarks = Bookmark.objects.filter(status=BookmarkStatus.READY)
        exports = BookmarkExporterService.export_all(bookmarks)
        serializer = BookmarkExportSerializer(exports, many=True)
        return Response(serializer.data)


# ======================================================================
# /listb Slash Command
# ======================================================================


class SlashListbView(APIView):
    """
    POST /nudgy/mattermost/slash/listb/

    Handles the /listb slash command. Returns recent bookmarks
    as a Markdown message or opens an interactive dialog for browsing.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle /listb slash command",
        responses={200: OpenApiResponse(description="Bookmark list message.")},
    )
    def post(self, request: Request) -> Response:
        trigger_id = request.data.get("trigger_id", "")
        user_id = request.data.get("user_id", "")
        channel_id = request.data.get("channel_id", "")
        text = (request.data.get("text", "") or "").strip().lower()

        logger.info(
            "Slash /listb received — user: %s, channel: %s, filter: %s",
            user_id,
            channel_id,
            text or "recent",
        )

        # Determine filter
        filters: dict = {}
        if text in ("github", "youtube", "reddit", "article", "pdf", "documentation", "website"):
            filters["bookmark_type"] = text
        elif text == "archived":
            filters["is_archived"] = True
        elif text == "unread":
            filters["is_archived"] = False
        # default: recent (no filter)

        bookmarks = BookmarkSearchService.search(filters)[:15]

        if not bookmarks:
            return Response(
                {"response_type": "ephemeral", "text": "📚 **No bookmarks found.**\n\nDM me a URL to save your first bookmark!"},
                status=status.HTTP_200_OK,
            )

        attachments = []
        for bk in bookmarks:
            tags_str = ", ".join(bk.tags.values_list("name", flat=True))
            desc = bk.description[:200] + ("…" if len(bk.description) > 200 else "") if bk.description else ""

            fields = [
                {"short": True, "title": "Type", "value": bk.get_bookmark_type_display()},
                {"short": True, "title": "Date", "value": bk.created_at.strftime("%Y-%m-%d")},
            ]
            if tags_str:
                fields.append({"short": False, "title": "Tags", "value": tags_str})

            actions = []
            if not bk.is_archived:
                actions.append({
                    "name": "Archive",
                    "integration": {
                        "url": request.build_absolute_uri("/may/mattermost/bookmark/dialog/submit/"),
                        "context": {"action": "archive", "external_id": str(bk.external_id)}
                    }
                })
            actions.append({
                "name": "Delete",
                "style": "danger",
                "integration": {
                    "url": request.build_absolute_uri("/may/mattermost/bookmark/dialog/submit/"),
                    "context": {"action": "delete", "external_id": str(bk.external_id)}
                }
            })

            attachments.append({
                "fallback": bk.title or bk.url,
                "color": "#6366f1",
                "title": bk.title or bk.url,
                "title_link": bk.url,
                "text": desc,
                "thumb_url": bk.image_url if bk.image_url else None,
                "fields": fields,
                "actions": actions
            })

        return Response({
            "response_type": "ephemeral",
            "text": "📚 **Recent Bookmarks**",
            "attachments": attachments
        }, status=status.HTTP_200_OK)


# ======================================================================
# Bookmark Dialog Views (for interactive actions)
# ======================================================================


class BookmarkDialogSubmitView(APIView):
    """
    POST /may/mattermost/bookmark/dialog/submit/

    Handles interactive dialog submissions and interactive button clicks 
    for bookmark actions (archive, delete).
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle bookmark dialog/button submission",
        responses={200: OpenApiResponse(description="Action result.")},
    )
    def post(self, request: Request) -> Response:
        payload = request.data
        context = payload.get("context", {})
        channel_id = payload.get("channel_id", "")

        logger.info(
            "Bookmark action submit — context: %s",
            context,
        )

        action_type = context.get("action")
        external_id = context.get("external_id")

        if not action_type or not external_id:
            logger.warning("Invalid action payload: %s", payload)
            return Response(status=status.HTTP_200_OK)

        # --- Archive action ---
        if action_type == "archive":
            try:
                bookmark = Bookmark.objects.get(external_id=external_id)
                bookmark.is_archived = True
                bookmark.save()
                return Response({"ephemeral_text": f"📦 **Bookmark archived:** {bookmark.title or bookmark.url}"}, status=status.HTTP_200_OK)
            except Bookmark.DoesNotExist:
                logger.warning("Bookmark %s not found for archive.", external_id)
                return Response({"ephemeral_text": "Bookmark not found."}, status=status.HTTP_200_OK)

        # --- Delete action ---
        elif action_type == "delete":
            try:
                bookmark = Bookmark.objects.get(external_id=external_id)
                title = bookmark.title or bookmark.url
                bookmark.delete()
                return Response({"ephemeral_text": f"🗑️ **Bookmark deleted:** {title}"}, status=status.HTTP_200_OK)
            except Bookmark.DoesNotExist:
                logger.warning("Bookmark %s not found for delete.", external_id)
                return Response({"ephemeral_text": "Bookmark not found."}, status=status.HTTP_200_OK)

        return Response(status=status.HTTP_200_OK)


# ======================================================================
# Helpers
# ======================================================================


def _type_emoji(bookmark_type: str) -> str:
    """Return an emoji for the bookmark type."""
    return {
        "website": "🌐",
        "article": "📰",
        "youtube": "▶️",
        "github": "🐙",
        "reddit": "🔴",
        "pdf": "📄",
        "documentation": "📖",
        "other": "🔗",
    }.get(bookmark_type, "🔗")
