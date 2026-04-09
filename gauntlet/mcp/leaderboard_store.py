"""Supabase-backed leaderboard persistence for the public API.

Stores Elo ratings in Supabase so they persist across Vercel serverless
invocations and are accessible via the REST API for the public leaderboard.

Table schema (create in Supabase SQL editor):

    create table gauntlet_leaderboard (
        model_name text primary key,
        rating float8 not null default 1500,
        wins int not null default 0,
        losses int not null default 0,
        draws int not null default 0,
        avg_tokens_sec float8,
        avg_quality float8,
        total_comparisons int not null default 0,
        last_seen timestamptz,
        updated_at timestamptz default now()
    );

    -- For sorted queries
    create index idx_leaderboard_rating on gauntlet_leaderboard (rating desc);
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("gauntlet.mcp.leaderboard")

_SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()


def _headers() -> dict[str, str]:
    return {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _table_url() -> str:
    return f"{_SUPABASE_URL}/rest/v1/gauntlet_leaderboard"


def is_available() -> bool:
    """Check if Supabase leaderboard storage is configured."""
    return bool(_SUPABASE_URL and _SUPABASE_KEY)


def get_leaderboard() -> list[dict]:
    """Fetch the full leaderboard sorted by rating (highest first)."""
    if not is_available():
        return []

    try:
        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params={"select": "*", "order": "rating.desc"},
            timeout=5,
        )
        resp.raise_for_status()
        rows = resp.json()

        return [
            {
                "name": r["model_name"],
                "rating": round(r.get("rating", 1500), 1),
                "wins": r.get("wins", 0),
                "losses": r.get("losses", 0),
                "draws": r.get("draws", 0),
                "avg_tokens_sec": round(r["avg_tokens_sec"], 1) if r.get("avg_tokens_sec") else None,
                "avg_quality": round(r["avg_quality"], 1) if r.get("avg_quality") else None,
                "total_comparisons": r.get("total_comparisons", 0),
                "win_rate": round(
                    r["wins"] / max(r["wins"] + r["losses"] + r["draws"], 1) * 100, 1
                ),
                "last_seen": r.get("last_seen"),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"Failed to fetch leaderboard: {e}")
        return []


def upsert_model(
    model_name: str,
    rating: float,
    wins: int,
    losses: int,
    draws: int,
    avg_tokens_sec: Optional[float],
    avg_quality: Optional[float],
    total_comparisons: int,
) -> None:
    """Insert or update a model's leaderboard entry."""
    if not is_available():
        return

    try:
        payload = {
            "model_name": model_name,
            "rating": round(rating, 1),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "avg_tokens_sec": round(avg_tokens_sec, 1) if avg_tokens_sec else None,
            "avg_quality": round(avg_quality, 1) if avg_quality else None,
            "total_comparisons": total_comparisons,
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        resp = httpx.post(
            _table_url(),
            headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to upsert leaderboard entry for {model_name}: {e}")


def sync_from_local(leaderboard_data: dict) -> None:
    """Sync a local leaderboard dict to Supabase.

    Called after each comparison to push updated ratings to the public store.
    """
    if not is_available():
        return

    for model in leaderboard_data.get("models", []):
        upsert_model(
            model_name=model["name"],
            rating=model.get("rating", 1500),
            wins=model.get("wins", 0),
            losses=model.get("losses", 0),
            draws=model.get("draws", 0),
            avg_tokens_sec=model.get("avg_tokens_sec"),
            avg_quality=model.get("avg_quality"),
            total_comparisons=model.get("total_comparisons", 0),
        )
