"""Shared submission helper for community leaderboard.

Handles HMAC signing, version tagging, and posting to the public API.
Used by cli/app.py, core/module_runner.py, and dashboard/server.py.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Optional

import httpx

from gauntlet import __version__

logger = logging.getLogger("gauntlet.submit")

_COMMUNITY_API = "https://gauntlet.basaltlabs.app/api/submit"
_SUBMIT_KEY = os.environ.get("GAUNTLET_SUBMIT_KEY", "gauntlet-community-2026")


def _sign_payload(body_bytes: bytes) -> str:
    """Generate HMAC-SHA256 signature for the payload."""
    return hmac.new(_SUBMIT_KEY.encode(), body_bytes, hashlib.sha256).hexdigest()


def submit_result(payload: dict, timeout: float = 10) -> Optional[httpx.Response]:
    """Submit a result payload to the community API with signing.

    Automatically injects cli_version and computes HMAC signature.
    Returns the response on success, None on failure.
    """
    # Inject version
    payload["cli_version"] = __version__

    body_bytes = json.dumps(payload).encode()
    signature = _sign_payload(body_bytes)

    try:
        resp = httpx.post(
            _COMMUNITY_API,
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Gauntlet-Signature": signature,
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.debug("Submit failed (%d): %s", resp.status_code, resp.text)
        return resp
    except Exception as e:
        logger.debug("Submit error: %s", e)
        return None
