"""
Service for downloading and validating bookmark preview images.

Downloads OG/Twitter preview images and favicons, validates content
type and size, and stores them as BookmarkAsset records.
"""

from __future__ import annotations

import logging
import uuid
from io import BytesIO
from pathlib import Path

import requests
from django.core.files.base import ContentFile

from bookmarks.models import AssetType, Bookmark, BookmarkAsset

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "image/svg+xml",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
DOWNLOAD_TIMEOUT = 15  # seconds

CONTENT_TYPE_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/svg+xml": ".svg",
}


class BookmarkImageService:
    """Downloads and stores preview images for bookmarks."""

    @classmethod
    def download_preview_image(cls, bookmark: Bookmark) -> BookmarkAsset | None:
        """
        Download the bookmark's preview image and store it as a BookmarkAsset.

        Tries the bookmark's image_url first. If that fails or is empty,
        falls back gracefully and returns None.
        """
        if not bookmark.image_url:
            logger.debug("No image_url for bookmark %s — skipping.", bookmark.external_id)
            return None

        asset = cls._download_and_store(
            bookmark=bookmark,
            image_url=bookmark.image_url,
            asset_type=AssetType.OG_IMAGE,
        )
        return asset

    @classmethod
    def download_favicon(cls, bookmark: Bookmark) -> BookmarkAsset | None:
        """Download the bookmark's favicon."""
        if not bookmark.favicon_url:
            return None

        return cls._download_and_store(
            bookmark=bookmark,
            image_url=bookmark.favicon_url,
            asset_type=AssetType.FAVICON,
        )

    @classmethod
    def _download_and_store(
        cls,
        bookmark: Bookmark,
        image_url: str,
        asset_type: str,
    ) -> BookmarkAsset | None:
        """Download an image URL and persist it as a BookmarkAsset."""
        logger.info(
            "Downloading %s for bookmark %s from %s",
            asset_type,
            bookmark.external_id,
            image_url,
        )

        try:
            resp = requests.get(
                image_url,
                headers={"User-Agent": _USER_AGENT},
                timeout=DOWNLOAD_TIMEOUT,
                stream=True,
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning(
                "Image download failed for %s — %s",
                bookmark.external_id,
                image_url,
                exc_info=True,
            )
            return None

        # Validate content type
        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            logger.warning(
                "Invalid content type %s for image %s",
                content_type,
                image_url,
            )
            return None

        # Stream and validate size
        chunks: list[bytes] = []
        total_size = 0
        try:
            for chunk in resp.iter_content(chunk_size=8192):
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE:
                    logger.warning(
                        "Image too large (>%d bytes) for %s",
                        MAX_FILE_SIZE,
                        image_url,
                    )
                    return None
                chunks.append(chunk)
        except Exception as e:
            logger.warning(
                "Failed to stream image %s for bookmark %s: %s",
                image_url,
                bookmark.external_id,
                e,
            )
            return None

        image_data = b"".join(chunks)
        if not image_data:
            logger.warning("Empty image data from %s", image_url)
            return None

        # Determine file extension
        ext = CONTENT_TYPE_TO_EXT.get(content_type, ".jpg")
        filename = f"{uuid.uuid4().hex}{ext}"

        # Create and save asset
        asset = BookmarkAsset(
            bookmark=bookmark,
            asset_type=asset_type,
            original_url=image_url,
        )
        asset.file.save(filename, ContentFile(image_data), save=True)

        logger.info(
            "Saved %s asset for bookmark %s (%d bytes) → %s",
            asset_type,
            bookmark.external_id,
            total_size,
            asset.file.name,
        )
        return asset
