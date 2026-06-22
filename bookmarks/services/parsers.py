"""
Provider-specific bookmark parsers.

Each parser enriches the bookmark's metadata dict and sets the
correct BookmarkType. Parsers are dispatched by domain.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from bookmarks.models import BookmarkType

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class BookmarkParserService:
    """
    Dispatches URL parsing to provider-specific handlers.

    Returns:
        (bookmark_type, extra_metadata)
    """

    @classmethod
    def parse(cls, url: str, domain: str) -> tuple[str, dict[str, Any]]:
        """
        Detect the provider from the domain and parse provider-specific metadata.
        """
        domain_lower = domain.lower()

        if "github.com" in domain_lower:
            return cls._parse_github(url)
        elif "youtube.com" in domain_lower or "youtu.be" in domain_lower:
            return cls._parse_youtube(url)
        elif "reddit.com" in domain_lower:
            return cls._parse_reddit(url)
        elif url.lower().rstrip("/").endswith(".pdf"):
            return BookmarkType.PDF, {}
        else:
            return BookmarkType.WEBSITE, {}

    # ------------------------------------------------------------------
    # GitHub
    # ------------------------------------------------------------------

    @classmethod
    def _parse_github(cls, url: str) -> tuple[str, dict[str, Any]]:
        """Extract GitHub repo metadata via the public API."""
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]

        if len(parts) < 2:
            return BookmarkType.GITHUB, {}

        owner, repo = parts[0], parts[1]
        api_url = f"https://api.github.com/repos/{owner}/{repo}"

        meta: dict[str, Any] = {
            "owner": owner,
            "repo_name": repo,
        }

        try:
            resp = requests.get(
                api_url,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github.v3+json"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                meta.update({
                    "description": data.get("description", ""),
                    "stars": data.get("stargazers_count", 0),
                    "forks": data.get("forks_count", 0),
                    "language": data.get("language", ""),
                    "topics": data.get("topics", []),
                    "open_issues": data.get("open_issues_count", 0),
                    "license": (data.get("license") or {}).get("spdx_id", ""),
                })
                logger.info("GitHub API success for %s/%s — ★%d", owner, repo, meta["stars"])
            else:
                logger.warning("GitHub API returned %d for %s", resp.status_code, api_url)
        except requests.RequestException:
            logger.warning("GitHub API failed for %s", api_url, exc_info=True)

        return BookmarkType.GITHUB, meta

    # ------------------------------------------------------------------
    # YouTube
    # ------------------------------------------------------------------

    @classmethod
    def _parse_youtube(cls, url: str) -> tuple[str, dict[str, Any]]:
        """Extract YouTube video ID and build thumbnail URL."""
        video_id = cls._extract_youtube_id(url)
        meta: dict[str, Any] = {}

        if video_id:
            meta["video_id"] = video_id
            meta["thumbnail"] = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            meta["embed_url"] = f"https://www.youtube.com/embed/{video_id}"

        return BookmarkType.YOUTUBE, meta

    @staticmethod
    def _extract_youtube_id(url: str) -> str | None:
        """Extract video ID from various YouTube URL formats."""
        parsed = urlparse(url)

        if parsed.hostname in ("youtu.be",):
            return parsed.path.strip("/") or None

        if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
            if parsed.path == "/watch":
                qs = parse_qs(parsed.query)
                ids = qs.get("v", [])
                return ids[0] if ids else None
            # /embed/<id> or /shorts/<id>
            match = re.match(r"/(embed|shorts)/([a-zA-Z0-9_-]+)", parsed.path)
            if match:
                return match.group(2)

        return None

    # ------------------------------------------------------------------
    # Reddit
    # ------------------------------------------------------------------

    @classmethod
    def _parse_reddit(cls, url: str) -> tuple[str, dict[str, Any]]:
        """Extract subreddit and author from Reddit URLs."""
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        meta: dict[str, Any] = {}

        # /r/<subreddit>/comments/<id>/<slug>/
        if len(parts) >= 2 and parts[0] == "r":
            meta["subreddit"] = parts[1]
        if len(parts) >= 5 and parts[2] == "comments":
            meta["post_id"] = parts[3]

        # Try to get author from page (lightweight — we already have OG data)
        return BookmarkType.REDDIT, meta
