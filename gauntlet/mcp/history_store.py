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
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:
    from gauntlet.core.system_info import SystemFingerprint

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
    fingerprint: Optional["SystemFingerprint"] = None,
) -> None:
    """Record a single model's test result to the history table.

    Args:
        fingerprint: Optional SystemFingerprint with hardware/runtime/model metadata.
            When provided, stored as hardware, runtime, and model_config JSONB columns
            for community filtering (e.g. "show results from Apple Silicon with Q4").
    """
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

        # Attach system fingerprint for community filtering
        if fingerprint is not None:
            hw, rt, mc = fingerprint.to_storage_dicts()
            payload["hardware"] = hw
            payload["runtime"] = rt
            payload["model_config"] = mc

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
            "select": "model_name,timestamp,overall_score,trust_score,grade,category_scores,total_probes,passed_probes,source,quick,hardware,runtime,model_config",
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


def _get_filtered_history(
    gpu_class: Optional[str] = None,
    quantization: Optional[str] = None,
    parameter_size: Optional[str] = None,
    provider: Optional[str] = None,
    model_family: Optional[str] = None,
    os_platform: Optional[str] = None,
    source: Optional[str] = None,
    exclude_source: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    """Fetch history rows with optional JSONB filters.

    Use source="mcp" to get only MCP self-test results.
    Use exclude_source="mcp" to get only community (local hardware) results.
    """
    if not is_available():
        return []

    try:
        params: dict = {
            "select": "model_name,timestamp,overall_score,trust_score,grade,category_scores,total_probes,passed_probes,source,quick,hardware,runtime,model_config",
            "order": "timestamp.desc",
            "limit": str(limit),
        }

        # Source filter: include or exclude specific sources
        if source:
            params["source"] = f"eq.{source}"
        elif exclude_source:
            params["source"] = f"neq.{exclude_source}"

        # JSONB arrow filters (Supabase PostgREST syntax)
        if gpu_class:
            params["hardware->>gpu_class"] = f"eq.{gpu_class}"
        if quantization:
            params["model_config->>quantization"] = f"ilike.*{quantization}*"
        if parameter_size:
            params["model_config->>parameter_size"] = f"ilike.*{parameter_size}*"
        if provider:
            params["runtime->>provider"] = f"eq.{provider}"
        if model_family:
            params["model_config->>family"] = f"ilike.*{model_family}*"
        if os_platform:
            params["hardware->>os_platform"] = f"eq.{os_platform}"

        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params=params,
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Failed to fetch filtered history: {e}")
        return []


def get_aggregated_stats(
    gpu_class: Optional[str] = None,
    quantization: Optional[str] = None,
    parameter_size: Optional[str] = None,
    provider: Optional[str] = None,
    model_family: Optional[str] = None,
    os_platform: Optional[str] = None,
    source: Optional[str] = None,
    exclude_source: Optional[str] = None,
    min_tests: int = 1,
) -> list[dict]:
    """Get aggregated stats per model for the public leaderboard graphs.

    Supports filtering by hardware, quantization, provider, source, etc.
    Use source="mcp" for MCP-only results. Use exclude_source="mcp" for
    community-only results (local hardware).
    """
    if not is_available():
        return []

    try:
        # Fetch history with optional filters
        rows = _get_filtered_history(
            gpu_class=gpu_class,
            quantization=quantization,
            parameter_size=parameter_size,
            provider=provider,
            model_family=model_family,
            os_platform=os_platform,
            source=source,
            exclude_source=exclude_source,
            limit=500,
        )
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
                    "gpu_classes": set(),
                    "quantizations": set(),
                    "platforms": set(),
                    "providers": set(),
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

            # Collect hardware diversity metadata
            hw = row.get("hardware") or {}
            rt = row.get("runtime") or {}
            mc = row.get("model_config") or {}
            if hw.get("gpu_class"):
                m["gpu_classes"].add(hw["gpu_class"])
            if mc.get("quantization"):
                m["quantizations"].add(mc["quantization"])
            if hw.get("os_platform"):
                m["platforms"].add(hw["os_platform"])
            if rt.get("provider"):
                m["providers"].add(rt["provider"])

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
            if m["test_count"] < min_tests:
                continue

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
                "history": list(reversed(m["history"])),
                "latest_timestamp": m["latest_timestamp"],
                # Hardware diversity: how many different setups tested this model
                "tested_on": {
                    "gpu_classes": sorted(m["gpu_classes"]),
                    "quantizations": sorted(m["quantizations"]),
                    "platforms": sorted(m["platforms"]),
                    "providers": sorted(m["providers"]),
                },
            })

        # Sort by avg_score descending
        result.sort(key=lambda x: x["avg_score"], reverse=True)
        return result
    except Exception as e:
        logger.warning(f"Failed to aggregate stats: {e}")
        return []
