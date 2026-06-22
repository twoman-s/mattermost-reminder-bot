"""
Background bookmark processor.

Runs metadata extraction, provider parsing, and image downloads
in a daemon thread so that the user gets an instant response.
"""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlparse

from bookmarks.models import Bookmark, BookmarkStatus
from bookmarks.services.images import BookmarkImageService
from bookmarks.services.metadata import BookmarkMetadataService
from bookmarks.services.parsers import BookmarkParserService

logger = logging.getLogger(__name__)


def process_bookmark_async(bookmark_id: int, channel_id: str = "") -> None:
    """
    Spawn a daemon thread to process the bookmark in the background.
    """
    thread = threading.Thread(
        target=_process_bookmark,
        args=(bookmark_id, channel_id),
        daemon=True,
        name=f"bookmark-processor-{bookmark_id}",
    )
    thread.start()
    logger.info("Spawned background processor for bookmark ID %d", bookmark_id)


def _process_bookmark(bookmark_id: int, channel_id: str) -> None:
    """
    Full bookmark enrichment pipeline:
      1. Fetch HTML metadata (OG, Twitter, title, description, favicon)
      2. Run provider-specific parser (GitHub, YouTube, Reddit, etc.)
      3. Download preview image
      4. Download favicon
      5. Update bookmark status → READY
      6. Send enriched preview back to Mattermost
    """
    try:
        bookmark = Bookmark.objects.get(pk=bookmark_id)
    except Bookmark.DoesNotExist:
        logger.error("Bookmark ID %d not found — aborting.", bookmark_id)
        return

    logger.info("Processing bookmark %s — %s", bookmark.external_id, bookmark.url)

    try:
        # 1. Metadata extraction
        meta = BookmarkMetadataService.fetch_metadata(bookmark.url)
        bookmark.title = meta.get("title", "") or bookmark.title
        bookmark.description = meta.get("description", "") or bookmark.description
        bookmark.image_url = meta.get("image_url", "") or bookmark.image_url
        bookmark.favicon_url = meta.get("favicon_url", "") or bookmark.favicon_url

        raw_meta = meta.get("raw_meta", {})

        # 2. Provider-specific parsing
        bookmark_type, provider_meta = BookmarkParserService.parse(bookmark.url, bookmark.domain)
        bookmark.bookmark_type = bookmark_type

        # For YouTube, use the thumbnail as image_url if we don't have one from OG
        if bookmark_type == "youtube" and not bookmark.image_url and provider_meta.get("thumbnail"):
            bookmark.image_url = provider_meta["thumbnail"]

        # For GitHub, use the provider description if OG didn't give us one
        if bookmark_type == "github" and not bookmark.description and provider_meta.get("description"):
            bookmark.description = provider_meta["description"]

        # Merge provider metadata into the metadata JSON
        bookmark.metadata = {**raw_meta, **provider_meta}

        # 3. Download preview image
        BookmarkImageService.download_preview_image(bookmark)

        # 4. Download favicon
        BookmarkImageService.download_favicon(bookmark)

        # 5. Mark as ready
        bookmark.status = BookmarkStatus.READY
        bookmark.save()

        logger.info(
            "Bookmark %s processed successfully — type=%s, title=%s",
            bookmark.external_id,
            bookmark.bookmark_type,
            bookmark.title[:60],
        )

        # 6. Send enriched preview to Mattermost (to the default channel)
        _send_enriched_preview(bookmark)

    except Exception:
        logger.error(
            "Bookmark processing failed for %s",
            bookmark.external_id,
            exc_info=True,
        )
        bookmark.status = BookmarkStatus.FAILED
        bookmark.save()


def _send_enriched_preview(bookmark: Bookmark) -> None:
    """Send the enriched bookmark preview back to the Mattermost channel."""
    from reminders.services.mattermost import MattermostService
    from django.conf import settings

    mm = MattermostService()
    # Always post to the designated bot channel rather than the DM chat
    channel_id = settings.MATTERMOST_BOOKMARKS_CHANNEL_ID

    lines = [
        "📚 **Bookmark Saved**",
        "",
        f"**Title:**\n{bookmark.title or bookmark.url}",
        "",
        f"**Type:**\n{bookmark.get_bookmark_type_display()}",
        "",
        f"**Domain:**\n{bookmark.domain}",
        "",
        f"**ID:**\nBK-{str(bookmark.external_id)[:8]}",
    ]

    # Provider-specific details
    meta = bookmark.metadata or {}
    if bookmark.bookmark_type == "github":
        if meta.get("stars") is not None:
            lines.append(f"\n**Stars:** {meta['stars']:,}")
        if meta.get("language"):
            lines.append(f"**Language:** {meta['language']}")
    elif bookmark.bookmark_type == "youtube":
        if meta.get("video_id"):
            lines.append(f"\n**Video ID:** {meta['video_id']}")
    elif bookmark.bookmark_type == "reddit":
        if meta.get("subreddit"):
            lines.append(f"\n**Subreddit:** r/{meta['subreddit']}")

    # Image preview (100x80 as requested)
    if bookmark.image_url:
        lines.append(f"\n![preview]({bookmark.image_url} =100x80)")

    message = "\n".join(lines)

    try:
        mm.send_channel_message(channel_id, message)
    except Exception:
        logger.error(
            "Failed to send enriched preview for bookmark %s",
            bookmark.external_id,
            exc_info=True,
        )
