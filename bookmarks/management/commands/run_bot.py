"""
Mattermost WebSocket bot listener.
Connects to Mattermost using the bot token, listens for direct messages,
and routes them to the bookmark processor.
"""

import asyncio
import json
import logging
import re
from urllib.parse import urlparse

import requests
import websockets
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from bookmarks.models import Bookmark, BookmarkStatus
from bookmarks.processor import process_bookmark_async

logger = logging.getLogger("bookmarks")

_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'\)\]]+",
    re.IGNORECASE,
)

class Command(BaseCommand):
    help = "Runs the Mattermost WebSocket listener to process DMs instantly."

    def handle(self, *args, **kwargs):
        logger.info("Starting Mattermost bot WebSocket listener...")

        base_url = settings.MATTERMOST_URL.rstrip("/")
        token = settings.MATTERMOST_BOT_TOKEN

        # Get Bot User ID via REST API
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.get(f"{base_url}/api/v4/users/me", headers=headers, timeout=10)
            resp.raise_for_status()
            bot_user_id = resp.json()["id"]
            logger.info("Bot authenticated as user ID: %s", bot_user_id)
        except Exception as e:
            logger.error("Failed to authenticate with Mattermost REST API: %s", e)
            return

        async def listen():
            ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/v4/websocket"
            logger.info("Connecting to WebSocket: %s", ws_url)
            
            try:
                async with websockets.connect(ws_url) as ws:
                    # Authenticate WebSocket
                    auth_req = {
                        "seq": 1,
                        "action": "authentication_challenge",
                        "data": {"token": token}
                    }
                    await ws.send(json.dumps(auth_req))
                    logger.info("WebSocket connected and auth challenge sent.")

                    async for message in ws:
                        await self.handle_message(message, bot_user_id, base_url, headers)
            except Exception as e:
                logger.error("WebSocket connection error: %s", e)
                # Retry could go here if needed
                
        asyncio.run(listen())

    async def handle_message(self, message: str, bot_user_id: str, base_url: str, headers: dict):
        try:
            event = json.loads(message)
            if event.get("event") == "posted":
                data = event.get("data", {})
                if "post" not in data:
                    return
                    
                post = json.loads(data["post"])
                channel_type = data.get("channel_type")
                user_id = post.get("user_id")
                channel_id = post.get("channel_id")
                text = post.get("message", "")

                # Only process direct messages
                if channel_type != "D":
                    return

                # Ignore our own messages and any bot/webhook messages
                if user_id == bot_user_id:
                    return
                if post.get("props", {}).get("from_bot") == "true":
                    return
                if post.get("props", {}).get("from_webhook") == "true":
                    return

                if "Bookmark deleted:" in text or "Bookmark Saved" in text or "Already bookmarked" in text:
                    return

                logger.info("WS DM received — user: %s, channel: %s", user_id, channel_id)

                urls = _URL_PATTERN.findall(text)
                if not urls:
                    return

                # Deduplicate
                seen = set()
                unique_urls = []
                for u in urls:
                    u = u.rstrip(".,;:!?)")
                    if u not in seen:
                        seen.add(u)
                        unique_urls.append(u)

                created_bookmarks = []
                duplicate_bookmarks = []

                # Execute DB operations in synchronous thread to avoid async issues with Django ORM
                # Because handle_message is async, we use sync_to_async or just rely on Django's 
                # support for async if possible. But simple DB access might block. We'll just block the WS briefly.
                for url in unique_urls:
                    domain = urlparse(url).netloc or ""
                    try:
                        with transaction.atomic():
                            bookmark = Bookmark.objects.create(
                                mattermost_user_id=user_id,
                                url=url,
                                domain=domain,
                                status=BookmarkStatus.PROCESSING,
                            )
                        created_bookmarks.append(bookmark)
                        logger.info("Created bookmark %s for URL %s", bookmark.external_id, url)
                        process_bookmark_async(bookmark.pk, channel_id)

                    except IntegrityError:
                        existing = Bookmark.objects.filter(url=url).first()
                        if existing:
                            duplicate_bookmarks.append(existing)

                # Do NOT send intermediate 'Processing' messages.
                # Only log them.
                if duplicate_bookmarks:
                    response_lines = []
                    for bk in duplicate_bookmarks:
                        response_lines.append(
                            f"🔄 **Already bookmarked**\n\n**Title:** {bk.title or bk.url}\n**Domain:** {bk.domain}\n**ID:** BK-{str(bk.external_id)[:8]}"
                        )
                    response_text = "\n\n---\n\n".join(response_lines)
                    requests.post(
                        f"{base_url}/api/v4/posts",
                        headers=headers,
                        json={"channel_id": channel_id, "message": response_text},
                        timeout=5
                    )
        except Exception as e:
            logger.error("Error processing message: %s", e, exc_info=True)
