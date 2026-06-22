"""
Service for searching and filtering bookmarks.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models import Q, QuerySet

from bookmarks.models import Bookmark

logger = logging.getLogger(__name__)


class BookmarkSearchService:
    """Builds filtered querysets for bookmark searches."""

    @classmethod
    def search(cls, filters: dict[str, Any]) -> QuerySet[Bookmark]:
        """
        Return a filtered and ordered queryset of bookmarks.

        Supported filter keys:
          - search: free text search across title, url, description, domain
          - domain: exact domain match
          - bookmark_type: exact type match
          - tag: tag slug
          - collection: collection name
          - is_archived: bool
          - status: bookmark status
        """
        qs = Bookmark.objects.all()

        # Free text search
        search_term = filters.get("search", "").strip()
        if search_term:
            qs = qs.filter(
                Q(title__icontains=search_term)
                | Q(url__icontains=search_term)
                | Q(description__icontains=search_term)
                | Q(domain__icontains=search_term)
            )

        # Domain filter
        domain = filters.get("domain", "").strip()
        if domain:
            qs = qs.filter(domain__iexact=domain)

        # Bookmark type filter
        bookmark_type = filters.get("bookmark_type", "").strip()
        if bookmark_type:
            qs = qs.filter(bookmark_type=bookmark_type)

        # Tag filter (by slug)
        tag = filters.get("tag", "").strip()
        if tag:
            qs = qs.filter(tags__slug=tag)

        # Collection filter (by name)
        collection = filters.get("collection", "").strip()
        if collection:
            qs = qs.filter(collections__name__iexact=collection)

        # Archived filter
        is_archived = filters.get("is_archived")
        if is_archived is not None:
            if isinstance(is_archived, str):
                is_archived = is_archived.lower() in ("true", "1", "yes")
            qs = qs.filter(is_archived=is_archived)

        # Status filter
        status = filters.get("status", "").strip()
        if status:
            qs = qs.filter(status=status)

        return qs.distinct().order_by("-created_at")
