"""
Pure, browser-free planners for human-like input.

Each planner turns a high-level intent (move here, type this, scroll that far)
into a deterministic list of low-level steps, given an injected ``random.Random``.
Keeping the maths here — separate from Playwright dispatch — makes it unit
testable without a browser.

Modelled on the behaviour that automation detectors score: curved motion with a
bell-shaped velocity profile, mid-flight micro-jitter, occasional
overshoot-and-correct, burst-y event timing, per-key hold/gap jitter with
realistic typos, and inertial scroll.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

Point = Tuple[float, float]


# --- mouse ----------------------------------------------------------------

@dataclass
class MouseStep:
    x: float
    y: float
    delay_ms: float  # sleep BEFORE dispatching this point


def _ease_in_out(t: float) -> float:
    """Accelerate then decelerate — bell-shaped velocity (not monotonic)."""
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


def _cubic_bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return x, y


def plan_mouse_path(
    start: Point,
    end: Point,
    rng,
    *,
    overshoot: bool = True,
) -> List[MouseStep]:
    """
    Curved, jittered, burst-timed pointer path from ``start`` to ``end``.

    - control points at 25%/75% pushed perpendicular to travel by ±0.3·dist
    - ease-in-out sampling (bell velocity)
    - sinusoidal jitter envelope: max wobble mid-flight, ~0 at the ends
    - 15% overshoot-then-correct with a settle pause
    - burst timing: most points fire back-to-back, a short sleep every 3-5
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    dist = math.hypot(dx, dy)
    if dist < 1:
        return [MouseStep(ex, ey, 0.0)]

    # unit perpendicular
    px, py = -dy / dist, dx / dist
    b1 = rng.uniform(-0.3, 0.3) * dist
    b2 = rng.uniform(-0.3, 0.3) * dist
    c1 = (sx + dx * 0.25 + px * b1, sy + dy * 0.25 + py * b1)
    c2 = (sx + dx * 0.75 + px * b2, sy + dy * 0.75 + py * b2)

    steps = max(25, min(80, round(dist / 8)))
    wobble_max = 1.5

    out: List[MouseStep] = []
    burst_left = rng.randint(3, 5)
    for i in range(steps + 1):
        t = _ease_in_out(i / steps)
        x, y = _cubic_bezier(start, c1, c2, end, t)
        envelope = math.sin(math.pi * i / steps)
        x += rng.uniform(-wobble_max, wobble_max) * envelope
        y += rng.uniform(-wobble_max, wobble_max) * envelope

        # burst timing: sleep only at burst boundaries
        delay = 0.0
        burst_left -= 1
        if burst_left <= 0:
            delay = rng.uniform(8, 18)
            burst_left = rng.randint(3, 5)
        out.append(MouseStep(x, y, delay))

    if overshoot and rng.random() < 0.15 and dist > 40:
        ang = math.atan2(dy, dx)
        over = rng.uniform(3, 6)
        ox = ex + math.cos(ang) * over
        oy = ey + math.sin(ang) * over
        out.append(MouseStep(ox, oy, rng.uniform(8, 18)))
        # settle, then correct back onto the target
        out.append(MouseStep(ex + rng.uniform(-2, 2), ey + rng.uniform(-2, 2),
                             rng.uniform(30, 70)))

    return out


def click_target(box: Tuple[float, float, float, float], rng, *, kind: str = "generic") -> Point:
    """
    Pick a click point inside an element box (x, y, w, h). Inputs are clicked
    near the text start (left), buttons near centre — never dead-centre every
    time, which is itself a tell.
    """
    x, y, w, h = box
    if kind == "input":
        fx = rng.uniform(0.05, 0.30)
    elif kind == "button":
        fx = rng.uniform(0.35, 0.65)
    else:
        fx = rng.uniform(0.20, 0.80)
    fy = rng.uniform(0.30, 0.70)
    return x + w * fx, y + h * fy


# --- keyboard -------------------------------------------------------------

# QWERTY physical neighbours for realistic typos.
NEARBY_KEYS = {
    'a': 'sqwz', 'b': 'vghn', 'c': 'xdfv', 'd': 'serfcx', 'e': 'wsdr',
    'f': 'drtgvc', 'g': 'ftyhbv', 'h': 'gyujnb', 'i': 'ujko', 'j': 'huikmn',
    'k': 'jiolm', 'l': 'kop', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp',
    'p': 'ol', 'q': 'wa', 'r': 'edft', 's': 'awedxz', 't': 'rfgy',
    'u': 'yhji', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghu',
    'z': 'asx',
}


@dataclass
class KeyOp:
    kind: str  # 'char' | 'backspace' | 'pause'
    char: str = ''
    hold_ms: float = 0.0
    pre_delay_ms: float = 0.0


def plan_typing(
    text: str,
    rng,
    *,
    typo_chance: float = 0.02,
    think_chance: float = 0.10,
) -> List[KeyOp]:
    """
    Per-character typing plan with hold/gap jitter, occasional "thinking"
    pauses, and physically-plausible typos that get noticed and corrected.
    """
    ops: List[KeyOp] = []
    for ch in text:
        pre = rng.gauss(70, 40)
        pre = max(15.0, pre)
        if rng.random() < think_chance:
            pre += rng.uniform(400, 1000)

        lower = ch.lower()
        if (
            rng.random() < typo_chance
            and lower in NEARBY_KEYS
            and lower == ch  # only for simple lowercase, keep it honest
        ):
            wrong = rng.choice(NEARBY_KEYS[lower])
            ops.append(KeyOp('char', wrong, rng.uniform(15, 35), pre))
            ops.append(KeyOp('pause', pre_delay_ms=rng.uniform(100, 300)))
            ops.append(KeyOp('backspace', pre_delay_ms=rng.uniform(50, 150),
                             hold_ms=rng.uniform(15, 35)))
            ops.append(KeyOp('char', ch, rng.uniform(15, 35),
                             rng.uniform(50, 150)))
        else:
            ops.append(KeyOp('char', ch, rng.uniform(15, 35), pre))
    return ops


# --- scroll ---------------------------------------------------------------

@dataclass
class ScrollStep:
    delta_y: float
    delay_ms: float


def plan_scroll(total_dy: float, rng) -> List[ScrollStep]:
    """
    Break one logical scroll into inertial wheel chunks with an
    accelerate -> cruise -> decelerate profile and an occasional overshoot.
    """
    direction = 1 if total_dy >= 0 else -1
    remaining = abs(total_dy)
    if remaining < 1:
        return []

    out: List[ScrollStep] = []
    base = rng.uniform(80, 130)
    accel = [0.4, 0.7]  # first chunks are smaller
    decel = [0.7, 0.4]

    emitted = 0.0
    # accelerate
    for f in accel:
        if emitted >= remaining:
            break
        d = min(base * f, remaining - emitted)
        out.append(ScrollStep(direction * d, rng.uniform(30, 80)))
        emitted += d
    # cruise
    while emitted < remaining * 0.85:
        d = base * rng.uniform(0.8, 1.2)
        d = min(d, remaining - emitted)
        out.append(ScrollStep(direction * d, rng.uniform(30, 80)))
        emitted += d
    # decelerate
    for f in decel:
        if emitted >= remaining:
            break
        d = min(base * f, remaining - emitted)
        out.append(ScrollStep(direction * d, rng.uniform(40, 90)))
        emitted += d
    if emitted < remaining:
        out.append(ScrollStep(direction * (remaining - emitted), rng.uniform(30, 80)))

    # 10% overshoot then a couple of corrective scrolls back
    if rng.random() < 0.10:
        over = rng.uniform(50, 150)
        out.append(ScrollStep(direction * over, rng.uniform(30, 80)))
        out.append(ScrollStep(-direction * over * 0.6, rng.uniform(300, 600)))
        out.append(ScrollStep(-direction * over * 0.4, rng.uniform(80, 200)))

    return out
