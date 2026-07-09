"""
Regression checks for the anti-detect hardening fixes.

Covers: download integrity verification, IP validation, geolocation
jitter/accuracy, font/voice retention, and scoped version rewriting.
Pure-Python, no network, no browser build required:  pytest tests/test_hardening.py
"""

import hashlib
import io
import math

import pytest

from camoufox.exceptions import IntegrityError
from camoufox.fingerprints import (
    _cast_to_properties,
    _generate_random_font_subset,
    _is_version_field,
    _load_os_fonts,
)
from camoufox.geolocation import _DEFAULT_ACCURACY_KM, _jitter_coords
from camoufox.ip import valid_ipv4, valid_ipv6
from camoufox.pkgman import verify_file_sha256
from camoufox.utils import derive_seed


# --- download integrity (P0) ---------------------------------------------

def test_sha256_match_rewinds_buffer():
    data = b'camoufox-payload'
    buf = io.BytesIO(data)
    verify_file_sha256(buf, hashlib.sha256(data).hexdigest())
    assert buf.tell() == 0  # left ready for the extractor


def test_sha256_mismatch_aborts():
    buf = io.BytesIO(b'tampered')
    with pytest.raises(IntegrityError):
        verify_file_sha256(buf, 'de' * 32)


def test_sha256_unknown_is_permitted():
    verify_file_sha256(io.BytesIO(b'x'), None)  # warns, does not raise


def test_sha256_case_insensitive():
    data = b'x'
    verify_file_sha256(io.BytesIO(data), hashlib.sha256(data).hexdigest().upper())


# --- IP validation (P2) ---------------------------------------------------

@pytest.mark.parametrize('ip,ok', [
    ('1.2.3.4', True), ('255.255.255.255', True),
    ('1.2.3.999', False), ('1.2.3', False), ('2001:db8::1', False),
])
def test_valid_ipv4(ip, ok):
    assert valid_ipv4(ip) is ok


@pytest.mark.parametrize('ip,ok', [
    ('2001:db8::1', True), ('::1', True),
    (':::::', False), ('gggg::1', False), ('1.2.3.4', False),
])
def test_valid_ipv6(ip, ok):
    assert valid_ipv6(ip) is ok


# --- geolocation jitter + accuracy (P2) -----------------------------------

def test_jitter_varies_and_stays_in_locality():
    lat, lon = 40.7128, -74.0060
    seen = set()
    max_km = 0.0
    for _ in range(1000):
        la, lo = _jitter_coords(lat, lon, _DEFAULT_ACCURACY_KM)
        seen.add((la, lo))
        d = math.hypot((la - lat) * 111, (lo - lon) * 111 * math.cos(math.radians(lat)))
        max_km = max(max_km, d)
    assert len(seen) > 900          # not a shared centroid anymore
    assert max_km <= 5.05           # never wanders out of the locality


def test_jitter_respects_small_accuracy():
    lat, lon = 51.5, -0.12
    for _ in range(200):
        la, lo = _jitter_coords(lat, lon, 1.0)
        d = math.hypot((la - lat) * 111, (lo - lon) * 111 * math.cos(math.radians(lat)))
        assert d <= 1.01


# --- font/voice retention (P1) --------------------------------------------

def test_font_subset_high_retention():
    full = len(_load_os_fonts()['win'])
    sizes = [len(_generate_random_font_subset('windows')) for _ in range(50)]
    assert min(sizes) >= 0.83 * full   # close to a real install, not decimated


# --- P0: per-context setters must not linger on window --------------------

def test_init_script_deletes_all_setters():
    from camoufox.fingerprints import _build_init_script
    # a minimal set of values; several setters get no value and would otherwise
    # never be called (and never self-destruct)
    js = _build_init_script({'navigatorPlatform': 'Win32'})
    for name in (
        'setNavigatorPlatform', 'setWebGLRenderer', 'setScreenDimensions',
        'setFontSpacingSeed', 'setSpeechVoices', 'setTimezone', 'setWebRTCIPv4',
    ):
        assert name in js
    # the cleanup loop that removes them all must be present
    assert 'delete w[' in js


# --- deterministic fingerprint seeds --------------------------------------

def test_derive_seed_is_deterministic_and_bounded():
    a = derive_seed('profile-A', 'canvas')
    assert a == derive_seed('profile-A', 'canvas')       # stable across calls
    assert 1 <= a <= 4_294_967_295
    # different slot / different base -> different seed
    assert a != derive_seed('profile-A', 'audio')
    assert a != derive_seed('profile-B', 'canvas')
    # accepts int bases too
    assert derive_seed(42, 'fonts') == derive_seed(42, 'fonts')


# --- scoped version rewrite (P2) ------------------------------------------

def test_version_field_detection():
    assert _is_version_field('navigator.userAgent')
    assert _is_version_field('navigator.oscpu')
    assert not _is_version_field('webGl:renderer')
    assert not _is_version_field('screen.width')


def test_version_rewrite_does_not_corrupt_renderer():
    out = {}
    _cast_to_properties(
        out,
        {'renderer': 'webGl:renderer', 'ua': 'navigator.userAgent'},
        {'renderer': 'GeForce GTX 150.0', 'ua': 'Mozilla Firefox/129.0'},
        ff_version='152',
    )
    assert out['webGl:renderer'] == 'GeForce GTX 150.0'  # untouched
    assert '152.0' in out['navigator.userAgent']          # UA still rewritten
