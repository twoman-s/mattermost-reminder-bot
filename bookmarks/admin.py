"""
Django admin configuration for the Bookmark Vault models.
"""

from django.contrib import admin

from bookmarks.models import Bookmark, BookmarkAsset, Collection, Tag


class BookmarkAssetInline(admin.TabularInline):
    model = BookmarkAsset
    extra = 0
    readonly_fields = ["asset_type", "original_url", "file", "downloaded_at"]


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "domain",
        "bookmark_type",
        "status",
        "is_archived",
        "mattermost_user_id",
        "created_at",
    ]
    list_filter = [
        "bookmark_type",
        "status",
        "is_archived",
    ]
    search_fields = [
        "title",
        "url",
        "domain",
        "description",
    ]
    readonly_fields = [
        "external_id",
        "domain",
        "image_url",
        "favicon_url",
        "metadata",
        "created_at",
        "updated_at",
    ]
    filter_horizontal = ["tags", "collections"]
    inlines = [BookmarkAssetInline]
    list_per_page = 30


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ["name", "color"]
    search_fields = ["name"]
