"""
Browser management: launches Playwright with a persistent profile so
authentication cookies/storage survive across runs. Captures the Discord
token and x-super-properties header from intercepted API traffic.
"""

import asyncio
from pathlib import Path
from typing import Tuple, Optional

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    Request,
)


class AuthenticationTimeoutError(Exception):
    """Raised when no Authorization header is captured within the grace period."""


async def launch_authenticated_context(
    profile_path: Path,
    headless: bool = False,
    wait_for_auth_seconds: int = 120,
) -> Tuple[BrowserContext, Page, str, str]:
    """
    Returns (context, page, token, super_properties).
    The context stays open — caller is responsible for closing it.
    """

    profile_path.mkdir(parents=True, exist_ok=True)

    playwright = await async_playwright().start()

    collected_token: Optional[str] = None
    collected_super: Optional[str] = None
    token_queue: asyncio.Queue[str] = asyncio.Queue()
    super_queue: asyncio.Queue[str] = asyncio.Queue()

    async def _collect_headers(request: Request) -> None:
        nonlocal collected_token, collected_super
        if "/api/" not in request.url:
            return
        headers = await request.all_headers()
        auth = headers.get("authorization", "")
        super_props = headers.get("x-super-properties", "")
        if auth and not collected_token:
            collected_token = auth
            token_queue.put_nowait(auth)
        if super_props and not collected_super:
            collected_super = super_props
            super_queue.put_nowait(super_props)

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_path),
        headless=headless,
        viewport={"width": 1280, "height": 900},
    )

    page = context.pages[0] if context.pages else await context.new_page()

    context.on("request", _collect_headers)

    await page.goto("https://discord.com/channels/@me", wait_until="domcontentloaded")

    if not token_queue.empty():
        token = await token_queue.get()
        super_props = await _wait_or_empty(super_queue, timeout=10.0)
        print("[ascension] session resumed from existing profile")
        return context, page, token, super_props or ""

    print(
        "[ascension] no active session detected. "
        "Please log in to Discord in the browser window, then perform any "
        "action (e.g. navigate to a channel) so we can capture API headers."
    )

    try:
        token = await asyncio.wait_for(token_queue.get(), timeout=wait_for_auth_seconds)
    except asyncio.TimeoutError:
        raise AuthenticationTimeoutError(
            f"No Discord API request captured within {wait_for_auth_seconds}s. "
            "Did you log in and interact with the page?"
        )

    super_props = await _wait_or_empty(super_queue, timeout=10.0)
    if not super_props:
        super_props = await _poll_super_properties_from_pages(context, timeout=30.0)

    print("[ascension] token and super-properties captured")
    return context, page, token, super_props or ""


async def _wait_or_empty(queue: asyncio.Queue, timeout: float) -> Optional[str]:
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def _poll_super_properties_from_pages(
    context: BrowserContext, timeout: float
) -> Optional[str]:
    waited = 0.0
    while waited < timeout:
        for candidate in context.pages:
            if "discord.com" not in candidate.url:
                continue
            try:
                result = await candidate.evaluate("""
                    (() => {
                        try {
                            const raw = localStorage.getItem('MultiStoreManagers');
                            if (!raw) return null;
                            const parsed = JSON.parse(raw);
                            const keys = Object.keys(parsed);
                            if (!keys.length) return null;
                            const first = JSON.parse(parsed[keys[0]]);
                            return first?.token || null;
                        } catch(_) { return null; }
                    })()
                """)
                if result and isinstance(result, str) and len(result) > 20:
                    return result
            except Exception:
                pass

        await asyncio.sleep(1.0)
        waited += 1.0

    return None

