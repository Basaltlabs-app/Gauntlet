"""Supabase-backed test history for live graphs.

Stores per-model test results over time so the public leaderboard can
show rolling averages, trends, and category breakdowns.

Table schema (create in Supabase SQL editor):

    create table gauntlet_test_history (
        id bigint generated always as identity primary key,
        model_name text not null,
        timestamp timestamptz not null default now(),
        overall_score float8,
        trust_score float8,
        grade text,
        category_scores jsonb,
        total_probes int,
        passed_probes int,
        source text not null default 'cli',
        quick boolean default false
    );

    create index idx_history_model on gauntlet_test_history (model_name, timestamp desc);
    create index idx_history_time on gauntlet_test_history (timestamp desc);
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("gauntlet.mcp.history")

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
    return f"{_SUPABASE_URL}/rest/v1/gauntlet_test_history"


def is_available() -> bool:
    return bool(_SUPABASE_URL and _SUPABASE_KEY)


def record_test_result(
    model_name: str,
    overall_score: float,
    trust_score: float,
    grade: str,
    category_scores: dict[str, float],
    total_probes: int,
    passed_probes: int,
    source: str = "cli",
    quick: bool = False,
) -> None:
    """Record a single model's test result to the history table."""
    if not is_available():
        return

    try:
        payload = {
            "model_name": model_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_score": round(overall_score * 100, 1) if overall_score <= 1.0 else round(overall_score, 1),
            "trust_score": round(trust_score, 1),
            "grade": grade,
            "category_scores": category_scores,
            "total_probes": total_probes,
            "passed_probes": passed_probes,
            "source": source,
            "quick": quick,
        }

        resp = httpx.post(
            _table_url(),
            headers=_headers(),
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
        logger.debug(f"Recorded test history for {model_name}")
    except Exception as e:
        logger.warning(f"Failed to record test history for {model_name}: {e}")


def get_model_history(
    model_name: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Fetch test history, optionally filtered by model.

    Returns rows sorted by timestamp descending.
    """
    if not is_available():
        return []

    try:
        params: dict = {
            "select": "model_name,timestamp,overall_score,trust_score,grade,category_scores,total_probes,passed_probes,source,quick",
            "order": "timestamp.desc",
            "limit": str(limit),
        }
        if model_name:
            params["model_name"] = f"eq.{model_name}"

        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params=params,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch test history: {e}")
        return []


def get_aggregated_stats() -> list[dict]:
    """Get aggregated stats per model for the public leaderboard graphs.

    Returns per-model: avg scores, test count, latest grade, category averages.
    """
    if not is_available():
        return []

    try:
        # Fetch all history (limited to last 500 entries for performance)
        rows = get_model_history(limit=500)
        if not rows:
            return []

        # Aggregate by model
        models: dict[str, dict] = {}
        for row in rows:
            name = row["model_name"]
            if name not in models:
                models[name] = {
                    "name": name,
                    "scores": [],
                    "trust_scores": [],
                    "grades": [],
                    "category_totals": {},
                    "category_counts": {},
                    "test_count": 0,
                    "latest_timestamp": row["timestamp"],
                    "history": [],
                }

            m = models[name]
            m["test_count"] += 1
            if row.get("overall_score") is not None:
                m["scores"].append(row["overall_score"])
            if row.get("trust_score") is not None:
                m["trust_scores"].append(row["trust_score"])
            if row.get("grade"):
                m["grades"].append(row["grade"])

            # Accumulate category scores for averaging
            cats = row.get("category_scores") or {}
            for cat, score in cats.items():
                if isinstance(score, (int, float)):
                    m["category_totals"][cat] = m["category_totals"].get(cat, 0) + score
                    m["category_counts"][cat] = m["category_counts"].get(cat, 0) + 1

            # Keep last 20 data points for sparkline
            if len(m["history"]) < 20:
                m["history"].append({
                    "timestamp": row["timestamp"],
                    "overall_score": row.get("overall_score"),
                    "trust_score": row.get("trust_score"),
                })

        # Build output
        result = []
        for name, m in models.items():
            avg_score = sum(m["scores"]) / len(m["scores"]) if m["scores"] else 0
            avg_trust = sum(m["trust_scores"]) / len(m["trust_scores"]) if m["trust_scores"] else 0

            # Category averages
            cat_avgs = {}
            for cat in m["category_totals"]:
                count = m["category_counts"].get(cat, 1)
                cat_avgs[cat] = round(m["category_totals"][cat] / count, 1)

            result.append({
                "name": name,
                "avg_score": round(avg_score, 1),
                "avg_trust": round(avg_trust, 1),
                "latest_grade": m["grades"][0] if m["grades"] else "?",
                "test_count": m["test_count"],
                "category_averages": cat_avgs,
                "history": list(reversed(m["history"])),  # chronological order
                "latest_timestamp": m["latest_timestamp"],
            })

        # Sort by avg_score descending
        result.sort(key=lambda x: x["avg_score"], reverse=True)
        return result
    except Exception as e:
        logger.warning(f"Failed to aggregate stats: {e}")
        return []
