"""
Human-like input for Camoufox (mouse, keyboard, scroll).

Planners (browser-free, unit-tested) live in ``_planner``; Playwright
dispatchers live in ``actions``. Events are replayed through Playwright's
trusted input API so they are ``isTrusted`` (dispatched via Juggler), which is
what behavioural bot-detectors score.

    from camoufox.human import move, click, type_text, scroll          # async
    from camoufox.human import move_sync, click_sync, type_text_sync   # sync
"""

from .actions import (
    click,
    click_at,
    click_at_sync,
    click_sync,
    move,
    move_sync,
    scroll,
    scroll_sync,
    type_text,
    type_text_sync,
)
from ._planner import plan_mouse_path, plan_scroll, plan_typing

__all__ = [
    "move",
    "click",
    "click_at",
    "type_text",
    "scroll",
    "move_sync",
    "click_sync",
    "click_at_sync",
    "type_text_sync",
    "scroll_sync",
    "plan_mouse_path",
    "plan_typing",
    "plan_scroll",
]
