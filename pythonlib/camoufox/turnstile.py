"""
Cloudflare Turnstile / interstitial solver.

Automates the interaction via Playwright:
  1. find the Turnstile iframe (src contains challenges.cloudflare.com),
  2. click the checkbox — NOT dead-centre, but the left ~15% where the box sits,
     via a humanized pointer path (trusted events),
  3. poll the injected `cf-turnstile-response` token until it gains a value
     (or the challenge disappears).

This only automates the *interaction*; whether a click actually passes depends
on the browser's own fingerprint/stealth (that's what the rest of Camoufox is
for). Managed/enterprise challenges may still require a real solve.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from .human.actions import click_at, click_at_sync

_IFRAME = 'iframe[src*="challenges.cloudflare.com"]'
# Turnstile injects one of these hidden inputs holding the solved token.
_TOKEN_SELECTORS = (
    'input[name="cf-turnstile-response"]',
    'input[name="cf_challenge_response"]',
)

# left-15%, vertical-centre — where the CF checkbox actually renders
_CLICK_FX = 0.15
_CLICK_FY = 0.5


async def _token_value(page: Any) -> Optional[str]:
    for sel in _TOKEN_SELECTORS:
        try:
            el = await page.query_selector(sel)
        except Exception:
            el = None
        if el:
            val = await el.get_attribute("value")
            if val:
                return val
    return None


async def solve_turnstile(
    page: Any,
    *,
    timeout: float = 30.0,
    seed: Optional[int] = None,
) -> bool:
    """
    Attempt to solve a Turnstile challenge on ``page``. Returns True if a token
    was obtained within ``timeout`` seconds.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    # already solved?
    if await _token_value(page):
        return True

    while loop.time() < deadline:
        frame_el = None
        try:
            frame_el = await page.query_selector(_IFRAME)
        except Exception:
            frame_el = None

        if frame_el:
            box = await frame_el.bounding_box()
            style = (await frame_el.get_attribute("style")) or ""
            if box and "display: none" not in style and box["width"] > 0:
                cx = box["x"] + box["width"] * _CLICK_FX
                cy = box["y"] + box["height"] * _CLICK_FY
                try:
                    await click_at(page, cx, cy, seed=seed)
                except Exception:
                    pass
                # give the widget time to validate before re-checking
                for _ in range(10):
                    if await _token_value(page):
                        return True
                    await asyncio.sleep(0.5)

        if await _token_value(page):
            return True
        await asyncio.sleep(0.5)

    return bool(await _token_value(page))


def solve_turnstile_sync(
    page: Any,
    *,
    timeout: float = 30.0,
    seed: Optional[int] = None,
) -> bool:
    """Sync variant of :func:`solve_turnstile`."""
    deadline = time.monotonic() + timeout

    def token() -> Optional[str]:
        for sel in _TOKEN_SELECTORS:
            try:
                el = page.query_selector(sel)
            except Exception:
                el = None
            if el:
                val = el.get_attribute("value")
                if val:
                    return val
        return None

    if token():
        return True

    while time.monotonic() < deadline:
        frame_el = None
        try:
            frame_el = page.query_selector(_IFRAME)
        except Exception:
            frame_el = None

        if frame_el:
            box = frame_el.bounding_box()
            style = frame_el.get_attribute("style") or ""
            if box and "display: none" not in style and box["width"] > 0:
                cx = box["x"] + box["width"] * _CLICK_FX
                cy = box["y"] + box["height"] * _CLICK_FY
                try:
                    click_at_sync(page, cx, cy, seed=seed)
                except Exception:
                    pass
                for _ in range(10):
                    if token():
                        return True
                    time.sleep(0.5)

        if token():
            return True
        time.sleep(0.5)

    return bool(token())
