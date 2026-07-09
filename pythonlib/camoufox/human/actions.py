"""
Playwright dispatchers for human-like input.

The planners in ``_planner`` produce the step lists; here we replay them through
Playwright's trusted input API (``page.mouse`` / ``page.keyboard`` / wheel),
NOT ``page.evaluate`` — so every event is ``isTrusted`` (dispatched via Juggler),
which is what behavioural detectors check.

Both async and sync variants are provided. Import the one matching your
Playwright API flavour.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Optional, Tuple

from ._planner import (
    click_target,
    plan_mouse_path,
    plan_scroll,
    plan_typing,
)

Point = Tuple[float, float]

# viewport-center fallback for the first move when we have no tracked position
_POS_ATTR = "_cf_mouse_pos"


def _get_pos(page: Any) -> Point:
    return getattr(page, _POS_ATTR, (0.0, 0.0))


def _set_pos(page: Any, pt: Point) -> None:
    try:
        setattr(page, _POS_ATTR, pt)
    except Exception:
        pass  # some proxies disallow attrs; position tracking is best-effort


def _rng(seed: Optional[int]) -> random.Random:
    return random.Random(seed)


# --- async ----------------------------------------------------------------

async def move(page: Any, x: float, y: float, *, seed: Optional[int] = None) -> None:
    rng = _rng(seed)
    for step in plan_mouse_path(_get_pos(page), (x, y), rng):
        if step.delay_ms:
            await asyncio.sleep(step.delay_ms / 1000)
        await page.mouse.move(step.x, step.y)
    _set_pos(page, (x, y))


async def click(
    page: Any,
    selector: str,
    *,
    kind: str = "generic",
    seed: Optional[int] = None,
) -> None:
    rng = _rng(seed)
    handle = await page.wait_for_selector(selector, state="visible")
    box = await handle.bounding_box()
    if not box:
        await handle.click()
        return
    tx, ty = click_target((box["x"], box["y"], box["width"], box["height"]), rng, kind=kind)
    for step in plan_mouse_path(_get_pos(page), (tx, ty), rng):
        if step.delay_ms:
            await asyncio.sleep(step.delay_ms / 1000)
        await page.mouse.move(step.x, step.y)
    _set_pos(page, (tx, ty))
    await asyncio.sleep(rng.uniform(0.06, 0.20))  # aim delay
    await page.mouse.down()
    await asyncio.sleep(rng.uniform(0.04, 0.15))   # hold
    await page.mouse.up()


async def click_at(page: Any, x: float, y: float, *, seed: Optional[int] = None) -> None:
    """Humanized click at absolute viewport coordinates."""
    rng = _rng(seed)
    for step in plan_mouse_path(_get_pos(page), (x, y), rng):
        if step.delay_ms:
            await asyncio.sleep(step.delay_ms / 1000)
        await page.mouse.move(step.x, step.y)
    _set_pos(page, (x, y))
    await asyncio.sleep(rng.uniform(0.06, 0.20))
    await page.mouse.down()
    await asyncio.sleep(rng.uniform(0.04, 0.15))
    await page.mouse.up()


async def type_text(
    page: Any,
    selector: str,
    text: str,
    *,
    click_first: bool = True,
    seed: Optional[int] = None,
) -> None:
    rng = _rng(seed)
    if click_first:
        await click(page, selector, kind="input", seed=seed)
    kb = page.keyboard
    for op in plan_typing(text, rng):
        if op.pre_delay_ms:
            await asyncio.sleep(op.pre_delay_ms / 1000)
        if op.kind == "char":
            await kb.press(op.char, delay=op.hold_ms)
        elif op.kind == "backspace":
            await kb.press("Backspace", delay=op.hold_ms)
        # 'pause' is just the pre_delay above


async def scroll(page: Any, delta_y: float, *, seed: Optional[int] = None) -> None:
    rng = _rng(seed)
    for step in plan_scroll(delta_y, rng):
        await page.mouse.wheel(0, step.delta_y)
        if step.delay_ms:
            await asyncio.sleep(step.delay_ms / 1000)


# --- sync -----------------------------------------------------------------

def move_sync(page: Any, x: float, y: float, *, seed: Optional[int] = None) -> None:
    rng = _rng(seed)
    for step in plan_mouse_path(_get_pos(page), (x, y), rng):
        if step.delay_ms:
            time.sleep(step.delay_ms / 1000)
        page.mouse.move(step.x, step.y)
    _set_pos(page, (x, y))


def click_sync(
    page: Any,
    selector: str,
    *,
    kind: str = "generic",
    seed: Optional[int] = None,
) -> None:
    rng = _rng(seed)
    handle = page.wait_for_selector(selector, state="visible")
    box = handle.bounding_box()
    if not box:
        handle.click()
        return
    tx, ty = click_target((box["x"], box["y"], box["width"], box["height"]), rng, kind=kind)
    for step in plan_mouse_path(_get_pos(page), (tx, ty), rng):
        if step.delay_ms:
            time.sleep(step.delay_ms / 1000)
        page.mouse.move(step.x, step.y)
    _set_pos(page, (tx, ty))
    time.sleep(rng.uniform(0.06, 0.20))
    page.mouse.down()
    time.sleep(rng.uniform(0.04, 0.15))
    page.mouse.up()


def click_at_sync(page: Any, x: float, y: float, *, seed: Optional[int] = None) -> None:
    """Humanized click at absolute viewport coordinates (sync)."""
    rng = _rng(seed)
    for step in plan_mouse_path(_get_pos(page), (x, y), rng):
        if step.delay_ms:
            time.sleep(step.delay_ms / 1000)
        page.mouse.move(step.x, step.y)
    _set_pos(page, (x, y))
    time.sleep(rng.uniform(0.06, 0.20))
    page.mouse.down()
    time.sleep(rng.uniform(0.04, 0.15))
    page.mouse.up()


def type_text_sync(
    page: Any,
    selector: str,
    text: str,
    *,
    click_first: bool = True,
    seed: Optional[int] = None,
) -> None:
    rng = _rng(seed)
    if click_first:
        click_sync(page, selector, kind="input", seed=seed)
    kb = page.keyboard
    for op in plan_typing(text, rng):
        if op.pre_delay_ms:
            time.sleep(op.pre_delay_ms / 1000)
        if op.kind == "char":
            kb.press(op.char, delay=op.hold_ms)
        elif op.kind == "backspace":
            kb.press("Backspace", delay=op.hold_ms)


def scroll_sync(page: Any, delta_y: float, *, seed: Optional[int] = None) -> None:
    rng = _rng(seed)
    for step in plan_scroll(delta_y, rng):
        page.mouse.wheel(0, step.delta_y)
        if step.delay_ms:
            time.sleep(step.delay_ms / 1000)
