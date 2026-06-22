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

        # Explicitly ignore our own notification strings
        if "Bookmark deleted:" in text or "Bookmark Saved" in text or "Already bookmarked" in text:
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
        return self._handle_command(request.data, request)

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle /listb slash command via GET",
        responses={200: OpenApiResponse(description="Bookmark list message.")},
    )
    def get(self, request: Request) -> Response:
        return self._handle_command(request.query_params, request)

    def _build_bookmark_dialog(self, submission: dict) -> dict:
        page_num = 1
        try:
            page_num = int(submission.get("page") or 1)
        except ValueError:
            pass

        page_size = 5
        try:
            page_size = int(submission.get("page_size") or 5)
        except ValueError:
            pass

        pagination_action = submission.get("pagination_action") or "current"
        if pagination_action == "prev":
            page_num = max(1, page_num - 1)
        elif pagination_action == "next":
            page_num = page_num + 1

        bk_qs = BookmarkSearchService.search({})
        total_count = bk_qs.count()

        from django.core.paginator import Paginator
        paginator = Paginator(bk_qs, page_size)

        if page_num > paginator.num_pages:
            page_num = paginator.num_pages
        if page_num < 1:
            page_num = 1

        page_obj = paginator.get_page(page_num) if total_count > 0 else []

        intro_lines = [
            f"Bookmark Vault ({total_count} total)",
            "---",
        ]

        manage_options = []

        if total_count > 0:
            for bk in page_obj:
                type_emoji = "🌐"
                if bk.bookmark_type == BookmarkType.GITHUB:
                    type_emoji = "🐙"
                elif bk.bookmark_type == BookmarkType.YOUTUBE:
                    type_emoji = "▶️"
                elif bk.bookmark_type == BookmarkType.REDDIT:
                    type_emoji = "👽"
                elif bk.bookmark_type == BookmarkType.PDF:
                    type_emoji = "📄"

                tags_str = ", ".join(bk.tags.values_list("name", flat=True))
                desc = bk.description[:120] + "…" if bk.description and len(bk.description) > 120 else (bk.description or "")
                
                title_clean = (bk.title or bk.url)[:60]
                
                img_md = ""
                if bk.image_url:
                    img_md = f"![img]({bk.image_url} =250x120)\n\n"
                
                intro_lines.append(
                    f"> {img_md}\n"
                    f">\n"
                    f"> ### {type_emoji} [{title_clean}]({bk.url})\n"
                    f"> {desc}\n"
                    f">\n"
                    f"> **🌐 {bk.domain}** • {bk.created_at.strftime('%Y-%m-%d')}\n"
                    f"> **🏷️ {tags_str or 'None'}**\n"
                    f">\n"
                    f"> ---\n"
                )

                manage_options.append({
                    "text": title_clean[:30],
                    "value": str(bk.external_id)
                })
        else:
            intro_lines.append("No bookmarks found. DM me a link to save one!")
            manage_options.append({"text": "No bookmarks available", "value": "none"})

        # Page options
        page_options = []
        num_pages = paginator.num_pages if total_count > 0 else 1
        for p in range(1, num_pages + 1):
            page_options.append({"text": f"Page {p}", "value": str(p)})

        # Elements
        elements = [
            {
                "display_name": "Page Size",
                "name": "page_size",
                "type": "select",
                "default": str(page_size),
                "refresh": True,
                "options": [
                    {"text": "5 items", "value": "5"},
                    {"text": "10 items", "value": "10"},
                    {"text": "15 items", "value": "15"},
                ],
            },
            {
                "display_name": "Select Page",
                "name": "page",
                "type": "select",
                "default": str(page_num),
                "refresh": True,
                "options": page_options,
            },
            {
                "display_name": "Pagination Actions",
                "name": "pagination_action",
                "type": "select",
                "default": "current",
                "refresh": True,
                "options": [
                    {"text": "Stay on Current Page", "value": "current"},
                    {"text": "◄ Previous Page", "value": "prev"},
                    {"text": "Next Page ►", "value": "next"},
                ],
            }
        ]

        if total_count > 0:
            elements.append({
                "display_name": "Select Bookmark",
                "name": "bookmark_to_manage",
                "type": "select",
                "default": submission.get("bookmark_to_manage") or "",
                "options": manage_options,
                "optional": True,
            })
            elements.append({
                "display_name": "Action",
                "name": "bookmark_action",
                "type": "select",
                "default": submission.get("bookmark_action") or "details",
                "options": [
                    {"text": "View Details (Not Implemented)", "value": "details"},
                    {"text": "Archive", "value": "archive"},
                    {"text": "Delete", "value": "delete"},
                ],
                "optional": True,
            })

        return {
            "callback_id": "list_bookmarks",
            "title": "Bookmark Vault",
            "submit_label": "Execute Action",
            "introduction_text": "\n".join(intro_lines)[:3000],  # Mattermost limit is 3000 chars for intro_text
            "elements": elements,
        }

    def _handle_command(self, payload: dict, request: Request) -> Response:
        trigger_id = payload.get("trigger_id", "")
        user_id = payload.get("user_id", "")
        
        if not trigger_id:
            return Response({"text": "Missing trigger_id."}, status=status.HTTP_200_OK)

        callback_url = request.build_absolute_uri("/may/mattermost/bookmark/dialog/submit/")
        
        dialog_data = self._build_bookmark_dialog({})
        
        mm_service = MattermostService()
        dialog_request = {
            "trigger_id": trigger_id,
            "url": callback_url,
            "dialog": dialog_data,
        }
        
        try:
            mm_service.post_open_dialog(dialog_request)
        except Exception:
            logger.error("Failed to open bookmark dialog", exc_info=True)
            return Response(
                {"response_type": "ephemeral", "text": "Failed to open dialog. Please ensure Mattermost is reachable."},
                status=status.HTTP_200_OK,
            )

        return Response(status=status.HTTP_200_OK)

# ======================================================================
# Bookmark Dialog Views (for interactive actions)
# ======================================================================


class BookmarkDialogRefreshView(APIView):
    """
    POST /may/mattermost/bookmark/dialog/refresh/
    Handles dynamic updates as the user pages through bookmarks.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle bookmark dialog dynamic refresh",
        responses={200: OpenApiResponse(description="Form representation JSON.")},
    )
    def post(self, request: Request) -> Response:
        payload = request.data
        submission: dict = payload.get("submission", {})
        
        logger.info("Bookmark dialog refresh received. Submission: %s", submission)

        listb_view = SlashListbView()
        dialog_data = listb_view._build_bookmark_dialog(submission)

        return Response(dialog_data, status=status.HTTP_200_OK)


class BookmarkDialogSubmitView(APIView):
    """
    POST /may/mattermost/bookmark/dialog/submit/

    Handles interactive dialog submissions for bookmark actions (archive, delete).
    """

    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mattermost"],
        summary="Handle bookmark dialog submission",
        responses={200: OpenApiResponse(description="Action result.")},
    )
    def post(self, request: Request) -> Response:
        payload = request.data
        submission = payload.get("submission", {})
        channel_id = payload.get("channel_id", "")
        user_id = payload.get("user_id", "")

        logger.info(
            "Bookmark dialog submit — submission: %s",
            submission,
        )

        action_type = submission.get("bookmark_action")
        external_id = submission.get("bookmark_to_manage")

        if not action_type or not external_id or external_id == "none":
            logger.warning("Invalid or empty action payload: %s", payload)
            return Response(status=status.HTTP_200_OK)

        mm_service = MattermostService()

        # --- Archive action ---
        if action_type == "archive":
            try:
                bookmark = Bookmark.objects.get(external_id=external_id)
                bookmark.is_archived = True
                bookmark.save()
                if channel_id:
                    mm_service.send_channel_message(
                        channel_id, f"📦 **Bookmark archived:** {bookmark.title or bookmark.url}"
                    )
            except Bookmark.DoesNotExist:
                logger.warning("Bookmark %s not found for archive.", external_id)

        # --- Delete action ---
        elif action_type == "delete":
            try:
                bookmark = Bookmark.objects.get(external_id=external_id)
                title = bookmark.title or bookmark.url
                bookmark.delete()
                if channel_id:
                    mm_service.send_channel_message(
                        channel_id, f"🗑️ **Bookmark deleted:** {title}"
                    )
            except Bookmark.DoesNotExist:
                logger.warning("Bookmark %s not found for delete.", external_id)

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
