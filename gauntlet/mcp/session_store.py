"""Session state persistence for serverless MCP deployment.

On Vercel, each request may hit a different container with no shared memory.
This module stores GauntletRunner state in Supabase so sessions survive
across invocations.

Requires SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables.

Table schema (create in Supabase SQL editor):

    create table gauntlet_sessions (
        session_id text primary key,
        state jsonb not null,
        created_at timestamptz default now(),
        updated_at timestamptz default now(),
        finished boolean default false
    );

    -- Auto-cleanup: sessions older than 24h
    create index idx_sessions_updated on gauntlet_sessions (updated_at);
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from gauntlet.mcp.runner import GauntletRunner

logger = logging.getLogger("gauntlet.mcp.sessions")

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def _headers() -> dict[str, str]:
    return {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _table_url() -> str:
    return f"{_SUPABASE_URL}/rest/v1/gauntlet_sessions"


def save_session(session_id: str, runner: GauntletRunner) -> None:
    """Persist runner state to Supabase."""
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        logger.debug("No Supabase credentials — skipping session save")
        return

    payload = {
        "session_id": session_id,
        "state": runner.to_dict(),
        "finished": runner.finished,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    resp = httpx.post(
        _table_url(),
        headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
        json=payload,
        timeout=5,
    )
    resp.raise_for_status()


def load_session(session_id: str) -> Optional[GauntletRunner]:
    """Load runner state from Supabase. Returns None if not found."""
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        return None

    resp = httpx.get(
        _table_url(),
        headers={**_headers(), "Prefer": "return=representation"},
        params={"session_id": f"eq.{session_id}", "select": "state"},
        timeout=5,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None

    return GauntletRunner.from_dict(rows[0]["state"])


def delete_session(session_id: str) -> None:
    """Remove a completed session from storage."""
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        return

    httpx.delete(
        _table_url(),
        headers=_headers(),
        params={"session_id": f"eq.{session_id}"},
        timeout=5,
    )


def cleanup_old_sessions(max_age_hours: int = 24) -> None:
    """Delete sessions older than max_age_hours."""
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        return

    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()

    httpx.delete(
        _table_url(),
        headers=_headers(),
        params={"updated_at": f"lt.{cutoff}"},
        timeout=10,
    )
