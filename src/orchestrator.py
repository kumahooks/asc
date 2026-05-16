"""
Orchestrator: async pipeline that polls Discord channels for invite links
and opens them in Playwright tabs.

Flow:
  1. Launch Chrome with persistent profile (always, for tabs)
  2. Capture token + x-super-properties from API traffic
  3. Seed: fetch 50 messages per channel, print invite links
  4. Poll: every 3s fetch last 5 messages per channel, open new links in tabs
"""

import asyncio
import re
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import sys

from playwright.async_api import BrowserContext

from src.config import Config
from src.browser import (
    launch_authenticated_context,
)
from src.api import DiscordClient, DiscordAPIError


VISITED_LINKS_PATH = Path("visited_links.txt")

POLL_INTERVAL = 3
POLL_COUNT = 5
INITIAL_FETCH_COUNT = 50

_INVITE_PATTERN = re.compile(
    r"https://ascension\.gg/user/invite/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)

_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")


_shutdown_requested = False


def _now() -> str:
    return datetime.now().strftime("%d/%m %H:%M:%S")


def _log(text: str) -> None:
    print(f"[{_now()}] {text}", flush=True)


def _signal_handler(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True
    _log("signal received, shutting down gracefully...")


async def main_async(config_path: Path) -> None:
    global _shutdown_requested

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    config = Config.from_file(config_path)

    _log("launching browser...")
    context, page, token, super_properties = await launch_authenticated_context(
        profile_path=config.profile_path,
        headless=False,
        wait_for_auth_seconds=config.wait_for_auth_seconds,
    )

    client: Optional[DiscordClient] = None

    try:
        client = DiscordClient(token, super_properties)

        all_channel_ids = [
            channel_id
            for server in config.servers
            for channel_id in server.channels
        ]

        seen: dict[str, set[str]] = {channel_id: set() for channel_id in all_channel_ids}

        visited_links = _load_visited_links()
        _log(f"loaded {len(visited_links)} previously visited links")

        # ── seed ──────────────────────────────────────────────────────────
        _log(f"seeding {len(all_channel_ids)} channels x {INITIAL_FETCH_COUNT} msgs...")

        for channel_id in all_channel_ids:
            if _shutdown_requested:
                break
            try:
                initial = client.fetch_messages(channel_id, limit=INITIAL_FETCH_COUNT)
            except DiscordAPIError as error:
                _log(f"channel {channel_id}: seed failed ({error})")
                continue

            for message in initial:
                message_id = message["id"]
                seen[channel_id].add(message_id)

                links = _maybe_process(channel_id, message)
                if links:
                    await _open_new_links(context, links, visited_links)

            _log(f"channel {channel_id}: seeded {len(initial)}")

        if _shutdown_requested:
            _log("shutting down after seed phase")
            return

        _log(f"polling every {POLL_INTERVAL}s x {POLL_COUNT} msgs")

        # ── poll loop ─────────────────────────────────────────────────────
        while not _shutdown_requested:
            for channel_id in all_channel_ids:
                if _shutdown_requested:
                    break
                try:
                    messages = client.fetch_messages(channel_id, limit=POLL_COUNT)
                except DiscordAPIError as error:
                    _log(f"channel {channel_id}: {error}")
                    continue

                _log(f"polled channel {channel_id}")

                for message in reversed(messages):
                    if _shutdown_requested:
                        break
                    message_id = message["id"]
                    if message_id in seen[channel_id]:
                        continue
                    seen[channel_id].add(message_id)

                    links = _maybe_process(channel_id, message)
                    if links:
                        await _open_new_links(context, links, visited_links)

            if _shutdown_requested:
                break

            await asyncio.sleep(POLL_INTERVAL)

    finally:
        _log("closing API client...")
        if client is not None:
            client.close()

        _log("closing browser context (this saves the profile)...")
        await context.close()
        _log("shutdown complete")


def _maybe_process(channel_id: str, message: dict) -> List[str]:
    """Check message for invite links. Returns list of matched invite URLs."""
    content = message.get("content", "") or ""
    embed_text = _extract_embed_text(message.get("embeds", []))

    combined = f"{content}\n{embed_text}"
    matches = _INVITE_PATTERN.findall(combined)

    if not matches:
        return []

    author = message.get("author", {})
    name = author.get("global_name") or author.get("username", "?")
    timestamp = message.get("timestamp", "")[:19].replace("T", " ")

    all_urls = _URL_PATTERN.findall(content + " " + embed_text)

    header = f"[{_now()}] {name} in {channel_id}:"
    print(header, flush=True)
    for url in all_urls:
        tag = " (MATCH)" if url in matches else ""
        print(f"  {url}{tag}", flush=True)
    print(flush=True)

    return matches


async def _open_new_links(
    context: BrowserContext,
    links: List[str],
    visited_links: set[str],
) -> None:
    """Open unvisited links in tabs. Focus browser window and play a sound
    on the first new link found."""
    new_links = [link for link in links if link not in visited_links]
    if not new_links:
        return

    _play_sound()
    first_page = None
    for link in new_links:
        visited_links.add(link)
        _save_visited_link(link)
        tab = await _open_tab(context, link, first_page)
        if first_page is None:
            first_page = tab


async def _open_tab(context: BrowserContext, url: str, focus_page=None):
    """Open a URL in a new background tab. If focus_page is given,
    return focus to that page after navigating. Otherwise, bring
    the new tab to front.
    Returns the new page object (or None on failure)."""
    _log(f"opening tab: {url[:100]}")
    try:
        new_page = await context.new_page()
        await new_page.goto(url, wait_until="domcontentloaded")
        if focus_page:
            await focus_page.bring_to_front()
        else:
            await new_page.bring_to_front()
        _log(f"tab loaded: {new_page.url[:80]}")
        return new_page
    except Exception as error:
        _log(f"tab failed: {error}")
        return None


def _play_sound() -> None:
    """Play beep.wav from the project root. Non-blocking, failure is silent."""
    sound_path = Path("beep.wav")
    if not sound_path.exists():
        return
    for cmd in (
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(sound_path)],
        ["flatpak", "run", "org.ffmpeg.ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(sound_path)],
    ):
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except FileNotFoundError:
            continue


def _load_visited_links() -> set[str]:
    """Load previously visited invite links from the tracking file."""
    if not VISITED_LINKS_PATH.exists():
        return set()
    links = set()
    with open(VISITED_LINKS_PATH) as file:
        for line in file:
            stripped = line.strip()
            if stripped:
                links.add(stripped)
    return links


def _save_visited_link(link: str) -> None:
    """Append a link to the visited tracking file."""
    VISITED_LINKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(VISITED_LINKS_PATH, "a") as file:
        file.write(link + "\n")


def _extract_embed_text(embeds: list) -> str:
    parts: List[str] = []
    for embed in embeds:
        title = embed.get("title", "")
        description = embed.get("description", "")
        if title:
            parts.append(title)
        if description:
            parts.append(description)
        for field in embed.get("fields", []):
            parts.append(field.get("name", ""))
            parts.append(field.get("value", ""))
    return "\n".join(parts)


def main() -> None:
    if len(sys.argv) < 2:
        config_path = Path("config.json")
    else:
        config_path = Path(sys.argv[1])

    if not config_path.exists():
        print(f"[ascension] config not found: {config_path}")
        print("[ascension] copy config.json.template to config.json and edit it")
        sys.exit(1)

    asyncio.run(main_async(config_path))


if __name__ == "__main__":
    main()
