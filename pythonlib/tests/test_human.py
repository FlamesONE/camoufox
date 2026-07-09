"""
Unit checks for the human-input planners and the Turnstile solver logic.
Browser-free: planners are pure; the solver is driven with a fake page.
  pytest tests/test_human.py
"""

import asyncio
import math
import random

import pytest

from camoufox.human._planner import (
    NEARBY_KEYS,
    click_target,
    plan_mouse_path,
    plan_scroll,
    plan_typing,
)


# --- mouse ---------------------------------------------------------------

def test_mouse_path_anchored_and_curved():
    rng = random.Random(1)
    path = plan_mouse_path((0, 0), (400, 300), rng, overshoot=False)
    assert len(path) >= 25
    # ends land on the target (last point is the destination, ~exactly)
    assert abs(path[-1].x - 400) < 2 and abs(path[-1].y - 300) < 2
    # curved: at least one mid point deviates from the straight line
    def dist_to_line(px, py):
        return abs(300 * px - 400 * py) / math.hypot(400, 300)
    assert max(dist_to_line(s.x, s.y) for s in path[1:-1]) > 3


def test_mouse_jitter_envelope_zero_at_ends():
    # With a straight (collinear) target the only deviation is jitter; the
    # sinusoidal envelope must keep the first/last mid-steps close to the line.
    rng = random.Random(7)
    path = plan_mouse_path((0, 0), (800, 0), rng, overshoot=False)
    ys = [abs(s.y) for s in path]
    # near the ends jitter ~0, mid-flight it is larger
    edge = max(ys[1], ys[2], ys[-2], ys[-3])
    mid = max(ys[len(ys) // 2 - 2: len(ys) // 2 + 2])
    assert mid >= edge


def test_mouse_burst_timing():
    rng = random.Random(3)
    path = plan_mouse_path((0, 0), (500, 400), rng, overshoot=False)
    delays = [s.delay_ms for s in path]
    # most points fire back-to-back (delay 0), some carry a burst sleep
    zeros = sum(1 for d in delays if d == 0)
    bursts = sum(1 for d in delays if d > 0)
    assert zeros > bursts > 0


def test_overshoot_returns_to_target():
    # force overshoot by seeding until it triggers
    for s in range(200):
        rng = random.Random(s)
        path = plan_mouse_path((0, 0), (600, 10), rng, overshoot=True)
        # overshoot adds 2 trailing points; final must still be the target
        if len(path) > round(600 / 8) + 1:
            assert abs(path[-1].x - 600) < 3 and abs(path[-1].y - 10) < 3
            return
    pytest.skip("overshoot did not trigger in sample")


def test_click_target_bias():
    rng = random.Random(0)
    xs_input = [click_target((0, 0, 100, 20), rng, kind="input")[0] for _ in range(200)]
    xs_button = [click_target((0, 0, 100, 20), rng, kind="button")[0] for _ in range(200)]
    # inputs cluster left, buttons cluster centre
    assert sum(xs_input) / 200 < sum(xs_button) / 200
    assert all(0 <= x <= 100 for x in xs_input + xs_button)


# --- keyboard ------------------------------------------------------------

def test_typing_emits_every_char():
    rng = random.Random(5)
    ops = plan_typing("hello", rng, typo_chance=0.0)
    chars = [o.char for o in ops if o.kind == "char"]
    assert "".join(chars) == "hello"
    assert all(o.pre_delay_ms >= 15 for o in ops if o.kind == "char")


def test_typing_typo_is_corrected():
    # force typos; a typo => wrong neighbor char, then backspace, then right char
    rng = random.Random(2)
    ops = plan_typing("aaaa", rng, typo_chance=1.0)
    # final reconstructed text (apply backspaces) must equal the intent
    buf = []
    for o in ops:
        if o.kind == "char":
            buf.append(o.char)
        elif o.kind == "backspace":
            if buf:
                buf.pop()
    assert "".join(buf) == "aaaa"
    # a wrong char came from the physical-neighbor map
    assert any(o.kind == "backspace" for o in ops)


# --- scroll --------------------------------------------------------------

def test_scroll_sums_to_total_and_has_phases():
    rng = random.Random(9)
    steps = plan_scroll(1000, rng)
    total = sum(s.delta_y for s in steps)
    # without overshoot the net equals the request; allow the overshoot case
    assert abs(total - 1000) < 200
    assert all(s.delay_ms > 0 for s in steps)
    assert len(steps) >= 3


def test_scroll_direction_negative():
    rng = random.Random(4)
    steps = plan_scroll(-500, rng)
    assert sum(s.delta_y for s in steps) < 0


# --- turnstile solver logic ---------------------------------------------

class _FakeEl:
    def __init__(self, value=None, box=None, style=""):
        self._value = value
        self._box = box
        self._style = style

    async def get_attribute(self, name):
        if name == "value":
            return self._value
        if name == "style":
            return self._style
        return None

    async def bounding_box(self):
        return self._box


class _FakePage:
    """Serves no token for N polls, then a token appears (as if solved)."""
    def __init__(self, solve_after=1):
        self.calls = 0
        self.solve_after = solve_after
        self.clicked = False
        # minimal mouse for click_at
        self.mouse = self._Mouse()

    class _Mouse:
        async def move(self, *a, **k): pass
        async def down(self): pass
        async def up(self): pass

    async def query_selector(self, sel):
        if "iframe" in sel:
            return _FakeEl(box={"x": 10, "y": 10, "width": 300, "height": 65})
        # token input
        self.calls += 1
        if self.calls >= self.solve_after:
            return _FakeEl(value="tok_123")
        return _FakeEl(value=None)


def test_turnstile_returns_true_when_token_appears():
    from camoufox.turnstile import solve_turnstile
    page = _FakePage(solve_after=2)
    ok = asyncio.run(solve_turnstile(page, timeout=5, seed=1))
    assert ok is True
