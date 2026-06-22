"""
Service for extracting metadata from URLs.

Fetches the HTML page and extracts:
  - <title>
  - OpenGraph (og:title, og:description, og:image)
  - Twitter Card (twitter:title, twitter:description, twitter:image)
  - Favicon
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Browser-like User-Agent to avoid 403s from sites that block bots
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class BookmarkMetadataService:
    """Fetches and parses HTML metadata from a URL."""

    TIMEOUT = 15  # seconds

    @classmethod
    def fetch_metadata(cls, url: str) -> dict[str, Any]:
        """
        Fetch the page at ``url`` and extract all available metadata.

        Returns a dict with keys:
          title, description, image_url, favicon_url, raw_meta
        """
        logger.info("Fetching metadata for %s", url)

        result: dict[str, Any] = {
            "title": "",
            "description": "",
            "image_url": "",
            "favicon_url": "",
            "raw_meta": {},
        }

        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=cls.TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.warning("Failed to fetch %s", url, exc_info=True)
            return result

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            logger.info("Non-HTML content type (%s) for %s — skipping parse.", content_type, url)
            return result

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception:
            logger.warning("HTML parse failed for %s", url, exc_info=True)
            return result

        # --- <title> ---
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            result["title"] = title_tag.string.strip()

        # --- OpenGraph ---
        og = cls._extract_og(soup)
        result["raw_meta"]["og"] = og

        # --- Twitter Card ---
        twitter = cls._extract_twitter(soup)
        result["raw_meta"]["twitter"] = twitter

        # --- Best title ---
        if og.get("og:title"):
            result["title"] = og["og:title"]
        elif twitter.get("twitter:title"):
            result["title"] = twitter["twitter:title"]

        # --- Best description ---
        if og.get("og:description"):
            result["description"] = og["og:description"]
        elif twitter.get("twitter:description"):
            result["description"] = twitter["twitter:description"]
        else:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                result["description"] = meta_desc["content"].strip()

        # --- Best image (priority: og:image > twitter:image > twitter:image:src) ---
        image_url = (
            og.get("og:image")
            or twitter.get("twitter:image")
            or twitter.get("twitter:image:src")
            or ""
        )
        if image_url:
            result["image_url"] = cls._make_absolute(image_url, url)

        # --- Favicon ---
        result["favicon_url"] = cls._extract_favicon(soup, url)

        logger.info(
            "Metadata extracted for %s — title=%s, has_image=%s",
            url,
            result["title"][:60],
            bool(result["image_url"]),
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_og(soup: BeautifulSoup) -> dict[str, str]:
        """Extract all og: meta tags."""
        data: dict[str, str] = {}
        for tag in soup.find_all("meta", attrs={"property": re.compile(r"^og:")}):
            prop = tag.get("property", "")
            content = tag.get("content", "").strip()
            if prop and content:
                data[prop] = content
        return data

    @staticmethod
    def _extract_twitter(soup: BeautifulSoup) -> dict[str, str]:
        """Extract all twitter: meta tags."""
        data: dict[str, str] = {}
        for tag in soup.find_all("meta", attrs={"name": re.compile(r"^twitter:")}):
            name = tag.get("name", "")
            content = tag.get("content", "").strip()
            if name and content:
                data[name] = content
        # Some sites use property= instead of name= for Twitter cards
        for tag in soup.find_all("meta", attrs={"property": re.compile(r"^twitter:")}):
            prop = tag.get("property", "")
            content = tag.get("content", "").strip()
            if prop and content and prop not in data:
                data[prop] = content
        return data

    @staticmethod
    def _extract_favicon(soup: BeautifulSoup, base_url: str) -> str:
        """Find the best favicon URL."""
        # Look for <link rel="icon"> or <link rel="shortcut icon">
        for rel in (["icon"], ["shortcut", "icon"], ["apple-touch-icon"]):
            link = soup.find("link", rel=rel)
            if link and link.get("href"):
                return BookmarkMetadataService._make_absolute(link["href"], base_url)
        # Fallback to /favicon.ico
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

    @staticmethod
    def _make_absolute(href: str, base_url: str) -> str:
        """Convert a potentially relative URL to absolute."""
        if href.startswith(("http://", "https://", "//")):
            if href.startswith("//"):
                scheme = urlparse(base_url).scheme
                return f"{scheme}:{href}"
            return href
        return urljoin(base_url, href)
