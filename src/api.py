"""
API client for Discord's HTTP API v9.

Authenticates with a user token and provides methods to fetch messages
from channels.
"""

import sys
import time
from typing import List, Optional

import httpx


DISCORD_API_BASE = "https://discord.com/api/v9"


def _build_user_agent() -> str:
    platform_strings = {
        "linux": "X11; Linux x86_64",
        "win32": "Windows NT 10.0; Win64; x64",
        "darwin": "Macintosh; Intel Mac OS X 10_15_7",
    }
    platform_part = platform_strings.get(sys.platform, "X11; Linux x86_64")
    return (
        f"Mozilla/5.0 ({platform_part}) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )


_UA = _build_user_agent()


class DiscordAPIError(Exception):
    """Raised when the Discord API returns a non-2xx status."""


class DiscordClient:
    """Thin wrapper around Discord's HTTP API."""

    def __init__(self, token: str, super_properties: str = "") -> None:
        self._token = token
        headers: dict[str, str] = {
            "Authorization": token,
            "User-Agent": _UA,
            "Accept": "application/json",
            "X-Discord-Locale": "en-US",
            "X-Debug-Options": "bugReporterEnabled",
        }
        if super_properties:
            headers["X-Super-Properties"] = super_properties

        self._transport = httpx.Client(
            base_url=DISCORD_API_BASE,
            headers=headers,
            timeout=httpx.Timeout(30.0),
        )

    def close(self) -> None:
        self._transport.close()

    def fetch_messages(
        self,
        channel_id: str,
        limit: int = 50,
        before: Optional[str] = None,
    ) -> List[dict[str, object]]:
        """
        Fetch *limit* messages from *channel_id*, optionally
        paginating *before* a given message ID.
        """
        params = {"limit": str(limit)}
        if before:
            params["before"] = before

        response = self._transport.get(
            f"/channels/{channel_id}/messages",
            params=params,
        )

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 5))
            print(f"[ascension] rate-limited, sleeping {retry_after:.1f}s")
            time.sleep(retry_after)
            return self.fetch_messages(channel_id, limit, before)

        if not response.is_success:
            raise DiscordAPIError(
                f"GET /channels/{channel_id}/messages -> {response.status_code}: "
                f"{response.text[:500]}"
            )

        return response.json()

