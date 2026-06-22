"""
Models for the Bookmark Vault module.

Stores bookmarks, downloaded assets, tags, and collections.
"""

import uuid

from django.db import models
from django.utils.text import slugify


class BookmarkType(models.TextChoices):
    """Content type classifications for bookmarks."""

    WEBSITE = "website", "Website"
    ARTICLE = "article", "Article"
    YOUTUBE = "youtube", "YouTube"
    GITHUB = "github", "GitHub"
    REDDIT = "reddit", "Reddit"
    PDF = "pdf", "PDF"
    DOCUMENTATION = "documentation", "Documentation"
    OTHER = "other", "Other"


class BookmarkStatus(models.TextChoices):
    """Processing status of a bookmark."""

    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class AssetType(models.TextChoices):
    """Types of downloaded bookmark assets."""

    OG_IMAGE = "og_image", "OpenGraph Image"
    FAVICON = "favicon", "Favicon"
    YOUTUBE_THUMBNAIL = "youtube_thumbnail", "YouTube Thumbnail"
    PDF_COVER = "pdf_cover", "PDF Cover"


class Tag(models.Model):
    """User-defined tag for organizing bookmarks."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Collection(models.Model):
    """Named collection for grouping bookmarks."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    color = models.CharField(
        max_length=7,
        blank=True,
        default="#6366f1",
        help_text="Hex color code (e.g. #6366f1).",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Bookmark(models.Model):
    """
    A saved bookmark with metadata, tags, and collections.

    Created instantly when a user DMs a URL. Metadata and images
    are fetched in a background thread and the status transitions
    from PROCESSING → READY.
    """

    external_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
        help_text="Public-facing UUID.",
    )

    mattermost_user_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Mattermost user ID of the bookmark creator.",
    )

    url = models.URLField(
        max_length=2048,
        unique=True,
        help_text="Original bookmarked URL.",
    )

    domain = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Extracted domain (e.g. github.com).",
    )

    title = models.CharField(max_length=500, blank=True, default="")
    description = models.TextField(blank=True, default="")

    image_url = models.URLField(
        max_length=2048,
        blank=True,
        default="",
        help_text="Remote preview image URL (OG/Twitter).",
    )

    favicon_url = models.URLField(
        max_length=2048,
        blank=True,
        default="",
        help_text="Remote favicon URL.",
    )

    bookmark_type = models.CharField(
        max_length=30,
        choices=BookmarkType.choices,
        default=BookmarkType.WEBSITE,
        db_index=True,
    )

    status = models.CharField(
        max_length=20,
        choices=BookmarkStatus.choices,
        default=BookmarkStatus.PROCESSING,
        db_index=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Provider-specific metadata (stars, forks, channel, etc.).",
    )

    is_archived = models.BooleanField(default=False, db_index=True)

    tags = models.ManyToManyField(
        Tag,
        blank=True,
        related_name="bookmarks",
    )

    collections = models.ManyToManyField(
        Collection,
        blank=True,
        related_name="bookmarks",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Bookmark"
        verbose_name_plural = "Bookmarks"

    def __str__(self) -> str:
        label = self.title or self.url
        return f"[{self.get_bookmark_type_display()}] {label}"


class BookmarkAsset(models.Model):
    """
    A locally downloaded asset associated with a bookmark.

    Examples: OG images, favicons, YouTube thumbnails.
    """

    bookmark = models.ForeignKey(
        Bookmark,
        on_delete=models.CASCADE,
        related_name="assets",
    )

    asset_type = models.CharField(
        max_length=30,
        choices=AssetType.choices,
    )

    original_url = models.URLField(max_length=2048)

    file = models.ImageField(upload_to="bookmarks/assets/")

    downloaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-downloaded_at"]

    def __str__(self) -> str:
        return f"{self.get_asset_type_display()} for {self.bookmark}"
