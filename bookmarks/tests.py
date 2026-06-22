"""
Tests for the Bookmark Vault module.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookmarks.models import (
    Bookmark,
    BookmarkAsset,
    BookmarkStatus,
    BookmarkType,
    Collection,
    Tag,
)
from bookmarks.services.exporter import BookmarkExporterService
from bookmarks.services.parsers import BookmarkParserService
from bookmarks.services.search import BookmarkSearchService


class BookmarkModelTests(TestCase):
    """Tests for bookmark model creation and defaults."""

    def test_create_bookmark(self) -> None:
        bk = Bookmark.objects.create(
            mattermost_user_id="user123",
            url="https://github.com/tiangolo/fastapi",
            domain="github.com",
        )
        self.assertIsNotNone(bk.external_id)
        self.assertEqual(bk.status, BookmarkStatus.PROCESSING)
        self.assertEqual(bk.bookmark_type, BookmarkType.WEBSITE)
        self.assertFalse(bk.is_archived)

    def test_unique_url(self) -> None:
        Bookmark.objects.create(
            mattermost_user_id="user1",
            url="https://example.com",
            domain="example.com",
        )
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Bookmark.objects.create(
                    mattermost_user_id="user2",
                    url="https://example.com",
                    domain="example.com",
                )

    def test_tag_creation(self) -> None:
        tag = Tag.objects.create(name="Python")
        self.assertEqual(tag.slug, "python")

    def test_collection_creation(self) -> None:
        col = Collection.objects.create(name="Homelab", color="#ff5733")
        self.assertEqual(str(col), "Homelab")


class ParserServiceTests(TestCase):
    """Tests for BookmarkParserService provider detection."""

    def test_github_detection(self) -> None:
        bk_type, meta = BookmarkParserService.parse(
            "https://github.com/tiangolo/fastapi",
            "github.com",
        )
        self.assertEqual(bk_type, BookmarkType.GITHUB)
        self.assertEqual(meta["owner"], "tiangolo")
        self.assertEqual(meta["repo_name"], "fastapi")

    def test_youtube_detection(self) -> None:
        bk_type, meta = BookmarkParserService.parse(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "www.youtube.com",
        )
        self.assertEqual(bk_type, BookmarkType.YOUTUBE)
        self.assertEqual(meta["video_id"], "dQw4w9WgXcQ")

    def test_youtube_short_url(self) -> None:
        bk_type, meta = BookmarkParserService.parse(
            "https://youtu.be/dQw4w9WgXcQ",
            "youtu.be",
        )
        self.assertEqual(bk_type, BookmarkType.YOUTUBE)
        self.assertEqual(meta["video_id"], "dQw4w9WgXcQ")

    def test_reddit_detection(self) -> None:
        bk_type, meta = BookmarkParserService.parse(
            "https://reddit.com/r/django/comments/abc123/test",
            "reddit.com",
        )
        self.assertEqual(bk_type, BookmarkType.REDDIT)
        self.assertEqual(meta["subreddit"], "django")

    def test_pdf_detection(self) -> None:
        bk_type, _ = BookmarkParserService.parse(
            "https://example.com/paper.pdf",
            "example.com",
        )
        self.assertEqual(bk_type, BookmarkType.PDF)

    def test_generic_website(self) -> None:
        bk_type, _ = BookmarkParserService.parse(
            "https://news.ycombinator.com",
            "news.ycombinator.com",
        )
        self.assertEqual(bk_type, BookmarkType.WEBSITE)


class SearchServiceTests(TestCase):
    """Tests for BookmarkSearchService filtering."""

    def setUp(self) -> None:
        self.bk1 = Bookmark.objects.create(
            mattermost_user_id="user1",
            url="https://github.com/test/repo",
            domain="github.com",
            title="Test Repo",
            bookmark_type=BookmarkType.GITHUB,
            status=BookmarkStatus.READY,
        )
        self.bk2 = Bookmark.objects.create(
            mattermost_user_id="user1",
            url="https://youtube.com/watch?v=test",
            domain="youtube.com",
            title="Test Video",
            bookmark_type=BookmarkType.YOUTUBE,
            status=BookmarkStatus.READY,
            is_archived=True,
        )

    def test_search_by_text(self) -> None:
        results = BookmarkSearchService.search({"search": "Repo"})
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first(), self.bk1)

    def test_filter_by_domain(self) -> None:
        results = BookmarkSearchService.search({"domain": "youtube.com"})
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first(), self.bk2)

    def test_filter_by_type(self) -> None:
        results = BookmarkSearchService.search({"bookmark_type": "github"})
        self.assertEqual(results.count(), 1)

    def test_filter_by_archived(self) -> None:
        results = BookmarkSearchService.search({"is_archived": True})
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first(), self.bk2)


class ExporterServiceTests(TestCase):
    """Tests for BookmarkExporterService markdown export."""

    def test_export_to_markdown(self) -> None:
        bk = Bookmark.objects.create(
            mattermost_user_id="user1",
            url="https://github.com/test/repo",
            domain="github.com",
            title="Test Repo",
            bookmark_type=BookmarkType.GITHUB,
            metadata={"stars": 1500, "language": "Python"},
        )
        md = BookmarkExporterService.to_markdown(bk)
        self.assertIn("title: \"Test Repo\"", md)
        self.assertIn("type: github", md)
        self.assertIn("url: https://github.com/test/repo", md)
        self.assertIn("Stars", md)
        self.assertIn("1,500", md)


class DMWebhookViewTests(APITestCase):
    """Tests for the DM webhook endpoint."""

    def test_dm_with_url_creates_bookmark(self) -> None:
        url = reverse("mattermost-dm-webhook")
        with patch("bookmarks.views.process_bookmark_async") as mock_proc:
            resp = self.client.post(url, {
                "user_id": "user_abc",
                "channel_id": "ch_123",
                "channel_type": "D",
                "text": "Check this out https://example.com/page",
            }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Bookmark Saved", resp.data["text"])
        self.assertTrue(Bookmark.objects.filter(url="https://example.com/page").exists())
        mock_proc.assert_called_once()

    def test_dm_without_url_returns_empty(self) -> None:
        url = reverse("mattermost-dm-webhook")
        resp = self.client.post(url, {
            "user_id": "user_abc",
            "channel_id": "ch_123",
            "channel_type": "D",
            "text": "Hello May!",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Bookmark.objects.count(), 0)

    def test_non_dm_ignored(self) -> None:
        url = reverse("mattermost-dm-webhook")
        resp = self.client.post(url, {
            "user_id": "user_abc",
            "channel_id": "ch_123",
            "channel_type": "O",
            "text": "https://example.com",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Bookmark.objects.count(), 0)

    def test_duplicate_url_returns_existing(self) -> None:
        Bookmark.objects.create(
            mattermost_user_id="user1",
            url="https://example.com",
            domain="example.com",
            title="Example",
            status=BookmarkStatus.READY,
        )
        url = reverse("mattermost-dm-webhook")
        with patch("bookmarks.views.process_bookmark_async"):
            resp = self.client.post(url, {
                "user_id": "user_abc",
                "channel_id": "ch_123",
                "channel_type": "D",
                "text": "https://example.com",
            }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Already bookmarked", resp.data["text"])
        self.assertEqual(Bookmark.objects.count(), 1)

    def test_multiple_urls_in_message(self) -> None:
        url = reverse("mattermost-dm-webhook")
        with patch("bookmarks.views.process_bookmark_async"):
            resp = self.client.post(url, {
                "user_id": "user_abc",
                "channel_id": "ch_123",
                "channel_type": "D",
                "text": "Two links https://one.com and https://two.com",
            }, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Bookmark.objects.count(), 2)


class BookmarkAPITests(APITestCase):
    """Tests for the bookmark REST API."""

    def setUp(self) -> None:
        self.bk = Bookmark.objects.create(
            mattermost_user_id="user1",
            url="https://github.com/test/repo",
            domain="github.com",
            title="Test Repo",
            bookmark_type=BookmarkType.GITHUB,
            status=BookmarkStatus.READY,
        )

    def test_list_bookmarks(self) -> None:
        resp = self.client.get("/nudgy/api/v1/bookmarks/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_retrieve_bookmark(self) -> None:
        resp = self.client.get(f"/nudgy/api/v1/bookmarks/{self.bk.external_id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["title"], "Test Repo")
        self.assertIn("metadata", resp.data)
        self.assertIn("assets", resp.data)

    def test_search_bookmarks(self) -> None:
        resp = self.client.get("/nudgy/api/v1/bookmarks/", {"search": "Repo"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_export_bookmarks(self) -> None:
        resp = self.client.get("/nudgy/api/v1/bookmarks/export/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertIn("filename", resp.data[0])
        self.assertIn("content", resp.data[0])


class SlashListbViewTests(APITestCase):
    """Tests for the /listb slash command."""

    def setUp(self) -> None:
        self.bk = Bookmark.objects.create(
            mattermost_user_id="user1",
            url="https://github.com/test/repo",
            domain="github.com",
            title="Test Repo",
            bookmark_type=BookmarkType.GITHUB,
            status=BookmarkStatus.READY,
        )

    def test_listb_returns_bookmarks(self) -> None:
        url = reverse("mattermost-slash-listb")
        resp = self.client.post(url, {
            "trigger_id": "t123",
            "user_id": "u123",
            "channel_id": "ch123",
            "text": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Test Repo", resp.data["text"])

    def test_listb_no_bookmarks(self) -> None:
        Bookmark.objects.all().delete()
        url = reverse("mattermost-slash-listb")
        resp = self.client.post(url, {
            "trigger_id": "t123",
            "user_id": "u123",
            "channel_id": "ch123",
            "text": "",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("No bookmarks found", resp.data["text"])

    def test_listb_filter_by_type(self) -> None:
        url = reverse("mattermost-slash-listb")
        resp = self.client.post(url, {
            "trigger_id": "t123",
            "user_id": "u123",
            "channel_id": "ch123",
            "text": "github",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Test Repo", resp.data["text"])
