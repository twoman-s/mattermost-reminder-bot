"""
Serializers for the Bookmark Vault API.
"""

from rest_framework import serializers

from bookmarks.models import Bookmark, BookmarkAsset, Collection, Tag


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "slug"]
        read_only_fields = ["id", "slug"]


class CollectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Collection
        fields = ["id", "name", "description", "color"]
        read_only_fields = ["id"]


class BookmarkAssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookmarkAsset
        fields = ["id", "asset_type", "original_url", "file", "downloaded_at"]
        read_only_fields = ["id", "downloaded_at"]


class BookmarkListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    tags = TagSerializer(many=True, read_only=True)
    collections = CollectionSerializer(many=True, read_only=True)

    class Meta:
        model = Bookmark
        fields = [
            "external_id",
            "url",
            "domain",
            "title",
            "description",
            "image_url",
            "favicon_url",
            "bookmark_type",
            "status",
            "is_archived",
            "tags",
            "collections",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "external_id",
            "domain",
            "image_url",
            "favicon_url",
            "status",
            "created_at",
            "updated_at",
        ]


class BookmarkDetailSerializer(serializers.ModelSerializer):
    """Full serializer with assets and metadata for detail views."""

    tags = TagSerializer(many=True, read_only=True)
    collections = CollectionSerializer(many=True, read_only=True)
    assets = BookmarkAssetSerializer(many=True, read_only=True)

    class Meta:
        model = Bookmark
        fields = [
            "external_id",
            "mattermost_user_id",
            "url",
            "domain",
            "title",
            "description",
            "image_url",
            "favicon_url",
            "bookmark_type",
            "status",
            "metadata",
            "is_archived",
            "tags",
            "collections",
            "assets",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "external_id",
            "mattermost_user_id",
            "domain",
            "image_url",
            "favicon_url",
            "status",
            "metadata",
            "created_at",
            "updated_at",
        ]


class BookmarkExportSerializer(serializers.Serializer):
    """Serializer for exported markdown files."""

    filename = serializers.CharField()
    content = serializers.CharField()
