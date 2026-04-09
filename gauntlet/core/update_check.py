"""Non-blocking update checker.

Checks PyPI for a newer version of gauntlet-cli and caches the result
for 24 hours to avoid hitting the network on every run.

The check runs in a background thread so it never delays startup.
Returns immediately with cached data or None.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

from gauntlet import __version__
from gauntlet.core.config import GAUNTLET_DIR


_CACHE_FILE = GAUNTLET_DIR / "update_cache.json"
_CACHE_TTL_SECONDS = 86400  # 24 hours
_PYPI_URL = "https://pypi.org/pypi/gauntlet-cli/json"
_TIMEOUT = 3  # seconds


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '1.3.1' into a comparable tuple."""
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return (0,)


def _read_cache() -> Optional[dict]:
    """Read cached update check result if still valid."""
    try:
        if _CACHE_FILE.exists():
            data = json.loads(_CACHE_FILE.read_text())
            if time.time() - data.get("checked_at", 0) < _CACHE_TTL_SECONDS:
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _write_cache(latest: str, current: str) -> None:
    """Cache the update check result."""
    try:
        GAUNTLET_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps({
            "latest": latest,
            "current": current,
            "checked_at": time.time(),
        }))
    except OSError:
        pass  # read-only filesystem (Vercel), skip


def _fetch_latest_version() -> Optional[str]:
    """Fetch the latest version from PyPI. Returns None on failure."""
    try:
        import httpx
        resp = httpx.get(_PYPI_URL, timeout=_TIMEOUT, follow_redirects=True)
        if resp.status_code == 200:
            return resp.json()["info"]["version"]
    except Exception:
        pass
    return None


def _do_check() -> None:
    """Background thread: fetch latest version from PyPI and cache it."""
    latest = _fetch_latest_version()
    if latest:
        _write_cache(latest, __version__)


def check_for_update() -> Optional[str]:
    """Check if a newer version is available. Non-blocking.

    Returns the latest version string if an update is available,
    or None if current version is up to date (or check failed).

    First call triggers a background fetch. Subsequent calls within
    24 hours return cached results instantly.
    """
    # Check cache first
    cached = _read_cache()
    if cached:
        latest = cached.get("latest", __version__)
        if _parse_version(latest) > _parse_version(__version__):
            return latest
        return None

    # No cache or expired: trigger background fetch
    thread = threading.Thread(target=_do_check, daemon=True)
    thread.start()

    # First run returns None (check is in progress).
    # Next invocation will have cached data.
    return None


def get_update_message() -> Optional[str]:
    """Get a formatted update message, or None if up to date.

    Safe to call from anywhere. Never blocks, never throws.
    """
    try:
        latest = check_for_update()
        if latest:
            return (
                f"Update available: v{__version__} -> v{latest}. "
                f"Run: pip install --upgrade gauntlet-cli"
            )
    except Exception:
        pass
    return None
