"""
Service for exporting bookmarks to Markdown.

Designed for future Obsidian vault synchronization.
"""

from __future__ import annotations

import logging
from typing import Any

from bookmarks.models import Bookmark

logger = logging.getLogger(__name__)


class BookmarkExporterService:
    """Exports bookmarks to Obsidian-compatible Markdown."""

    @classmethod
    def to_markdown(cls, bookmark: Bookmark) -> str:
        """
        Convert a single bookmark to a Markdown document with YAML frontmatter.
        """
        tags = list(bookmark.tags.values_list("slug", flat=True))
        collections = list(bookmark.collections.values_list("name", flat=True))

        # Build frontmatter
        lines = [
            "---",
            f"title: \"{cls._escape_yaml(bookmark.title)}\"",
            f"type: {bookmark.bookmark_type}",
            f"url: {bookmark.url}",
            f"domain: {bookmark.domain}",
            f"saved: {bookmark.created_at.strftime('%Y-%m-%d')}",
            f"status: {bookmark.status}",
        ]

        if tags:
            lines.append("tags:")
            for tag in tags:
                lines.append(f"  - {tag}")

        if collections:
            lines.append("collections:")
            for col in collections:
                lines.append(f"  - {col}")

        if bookmark.image_url:
            lines.append(f"image: {bookmark.image_url}")

        lines.append("---")
        lines.append("")

        # Preview image
        if bookmark.image_url:
            lines.append(f"![Preview]({bookmark.image_url})")
            lines.append("")

        # Title & description
        lines.append(f"# {bookmark.title or bookmark.url}")
        lines.append("")

        if bookmark.description:
            lines.append(bookmark.description)
            lines.append("")

        # Link
        lines.append(f"**URL:** [{bookmark.domain}]({bookmark.url})")
        lines.append("")

        # Provider-specific metadata
        meta_section = cls._format_metadata(bookmark)
        if meta_section:
            lines.append("## Metadata")
            lines.append("")
            lines.append(meta_section)
            lines.append("")

        # Placeholder sections for user notes
        lines.append("## Notes")
        lines.append("")

        return "\n".join(lines)

    @classmethod
    def export_all(cls, bookmarks) -> list[dict[str, str]]:
        """
        Export multiple bookmarks to a list of {filename, content} dicts.
        """
        results = []
        for bk in bookmarks:
            safe_title = cls._safe_filename(bk.title or str(bk.external_id))
            results.append({
                "filename": f"{safe_title}.md",
                "content": cls.to_markdown(bk),
            })
        return results

    @staticmethod
    def _escape_yaml(value: str) -> str:
        """Escape double quotes in YAML strings."""
        return value.replace('"', '\\"')

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Sanitize a string for use as a filename."""
        import re
        name = re.sub(r'[<>:"/\\|?*]', "", name)
        name = name.strip(". ")
        return name[:100] or "untitled"

    @classmethod
    def _format_metadata(cls, bookmark: Bookmark) -> str:
        """Format provider-specific metadata as Markdown."""
        meta = bookmark.metadata or {}
        lines: list[str] = []

        if bookmark.bookmark_type == "github":
            if meta.get("stars") is not None:
                lines.append(f"- **Stars:** {meta['stars']:,}")
            if meta.get("forks") is not None:
                lines.append(f"- **Forks:** {meta['forks']:,}")
            if meta.get("language"):
                lines.append(f"- **Language:** {meta['language']}")
            if meta.get("owner"):
                lines.append(f"- **Owner:** {meta['owner']}")
            if meta.get("license"):
                lines.append(f"- **License:** {meta['license']}")

        elif bookmark.bookmark_type == "youtube":
            if meta.get("channel"):
                lines.append(f"- **Channel:** {meta['channel']}")
            if meta.get("duration"):
                lines.append(f"- **Duration:** {meta['duration']}")
            if meta.get("video_id"):
                lines.append(f"- **Video ID:** {meta['video_id']}")

        elif bookmark.bookmark_type == "reddit":
            if meta.get("subreddit"):
                lines.append(f"- **Subreddit:** r/{meta['subreddit']}")
            if meta.get("author"):
                lines.append(f"- **Author:** u/{meta['author']}")

        return "\n".join(lines)
