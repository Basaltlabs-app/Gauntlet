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
    probe_details: Optional[dict] = None,
    attestation: Optional[dict] = None,
    hardware_tier: str = "",
) -> None:
    """Record a single model's test result to the history table.

    Args:
        fingerprint: Optional SystemFingerprint with hardware/runtime/model metadata.
            When provided, stored as hardware, runtime, and model_config JSONB columns
            for community filtering (e.g. "show results from Apple Silicon with Q4").
        probe_details: Optional per-module probe-level breakdown. Dict mapping
            module_name -> list of {id, name, passed, score, severity, reason, duration_s}.
            Stored as JSONB for drill-down display on the community dashboard.
        attestation: Optional attestation dict (Phase 1.3) with version, fingerprint,
            and provenance metadata. Stored as JSONB.
        hardware_tier: Top-level hardware tier string for indexing/filtering.
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

        # Attach probe-level detail for drill-down display
        if probe_details:
            payload["probe_details"] = probe_details

        # Attach attestation for provenance tracking (Phase 1.3)
        if attestation:
            payload["attestation"] = attestation
        if hardware_tier:
            payload["hardware_tier"] = hardware_tier

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
    ram_bucket: Optional[str] = None,
    vram_bucket: Optional[str] = None,
    device_class: Optional[str] = None,
    gpu_name: Optional[str] = None,
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
            "select": "model_name,timestamp,overall_score,trust_score,grade,category_scores,total_probes,passed_probes,source,quick,hardware,runtime,model_config,probe_details",
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

        # Extended filters (new enriched fields)
        if ram_bucket:
            params["hardware->>ram_bucket"] = f"eq.{ram_bucket}"
        if vram_bucket:
            params["hardware->>vram_bucket"] = f"eq.{vram_bucket}"
        if device_class:
            params["hardware->>device_class"] = f"eq.{device_class}"
        if gpu_name:
            params["hardware->>gpu_name"] = f"ilike.*{gpu_name}*"

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
    ram_bucket: Optional[str] = None,
    vram_bucket: Optional[str] = None,
    device_class: Optional[str] = None,
    gpu_name: Optional[str] = None,
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
            ram_bucket=ram_bucket,
            vram_bucket=vram_bucket,
            device_class=device_class,
            gpu_name=gpu_name,
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


def get_community_stats() -> dict:
    """Get aggregate community statistics for the stats bar."""
    if not is_available():
        return {}

    try:
        rows = _get_filtered_history(exclude_source="mcp", limit=1000)
        if not rows:
            return {"total_tests": 0, "unique_models": 0}

        models = set()
        gpu_dist: dict[str, int] = {}
        ram_dist: dict[str, int] = {}
        os_dist: dict[str, int] = {}
        quant_dist: dict[str, int] = {}
        device_dist: dict[str, int] = {}
        configs = set()

        for row in rows:
            models.add(row["model_name"])
            hw = row.get("hardware") or {}
            mc = row.get("model_config") or {}

            gpu = hw.get("gpu_class", "unknown")
            gpu_dist[gpu] = gpu_dist.get(gpu, 0) + 1

            ram = hw.get("ram_bucket", "unknown")
            ram_dist[ram] = ram_dist.get(ram, 0) + 1

            osp = hw.get("os_platform", "unknown")
            os_dist[osp] = os_dist.get(osp, 0) + 1

            quant = mc.get("quantization", "unknown")
            quant_dist[quant] = quant_dist.get(quant, 0) + 1

            device = hw.get("device_class", "unknown")
            device_dist[device] = device_dist.get(device, 0) + 1

            configs.add(f"{gpu}_{ram}_{quant}")

        model_counts: dict[str, int] = {}
        for row in rows:
            n = row["model_name"]
            model_counts[n] = model_counts.get(n, 0) + 1
        most_tested = max(model_counts, key=model_counts.get) if model_counts else ""

        return {
            "total_tests": len(rows),
            "unique_models": len(models),
            "unique_configs": len(configs),
            "most_tested_model": most_tested,
            "gpu_distribution": dict(sorted(gpu_dist.items(), key=lambda x: x[1], reverse=True)),
            "ram_distribution": dict(sorted(ram_dist.items(), key=lambda x: x[1], reverse=True)),
            "os_distribution": dict(sorted(os_dist.items(), key=lambda x: x[1], reverse=True)),
            "quantization_distribution": dict(sorted(quant_dist.items(), key=lambda x: x[1], reverse=True)),
            "device_distribution": dict(sorted(device_dist.items(), key=lambda x: x[1], reverse=True)),
        }
    except Exception as e:
        logger.warning(f"Failed to get community stats: {e}")
        return {}


def get_tier_leaderboard(tier: str, limit: int = 50) -> list[dict]:
    """Get ranked models within a hardware tier with statistics.

    Queries rows matching the given hardware_tier, groups by model_name,
    computes ScoreStatistics per model, and returns ranked by mean score.

    Args:
        tier: One of CLOUD, CONSUMER_HIGH, CONSUMER_MID, CONSUMER_LOW, EDGE.
        limit: Maximum number of models to return.

    Returns:
        List of dicts with model_name, mean, ci_lower, ci_upper,
        sample_size, grade, is_reliable -- sorted by mean descending.
    """
    if not is_available():
        return []

    try:
        from gauntlet.core.statistics import compute_statistics

        params: dict = {
            "select": "model_name,overall_score,grade,hardware_tier",
            "order": "timestamp.desc",
            "limit": "1000",
            "hardware_tier": f"eq.{tier}",
        }

        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params=params,
            timeout=5,
        )
        resp.raise_for_status()
        rows = resp.json()

        if not rows:
            return []

        # Group by model
        model_scores: dict[str, list[float]] = {}
        model_grades: dict[str, list[str]] = {}
        for row in rows:
            name = row["model_name"]
            if name not in model_scores:
                model_scores[name] = []
                model_grades[name] = []
            if row.get("overall_score") is not None:
                model_scores[name].append(row["overall_score"])
            if row.get("grade"):
                model_grades[name].append(row["grade"])

        # Compute statistics per model
        result = []
        for name, scores in model_scores.items():
            if not scores:
                continue
            stats = compute_statistics(scores)
            if stats is None:
                continue
            result.append({
                "model_name": name,
                "mean": stats.mean,
                "ci_lower": stats.ci_lower,
                "ci_upper": stats.ci_upper,
                "sample_size": stats.sample_size,
                "grade": model_grades[name][0] if model_grades[name] else "?",
                "is_reliable": stats.is_reliable,
            })

        # Rank by mean descending
        result.sort(key=lambda x: x["mean"], reverse=True)
        return result[:limit]
    except Exception as e:
        logger.warning(f"Failed to get tier leaderboard for {tier}: {e}")
        return []


def get_tier_distribution() -> dict:
    """Get aggregate statistics per hardware tier.

    Returns the 'Steam hardware survey' view: unique models, total tests,
    and average score per tier.
    """
    if not is_available():
        return {"tiers": [], "total_submissions": 0, "last_updated": None}

    try:
        params: dict = {
            "select": "hardware_tier,model_name,overall_score,timestamp",
            "order": "timestamp.desc",
            "limit": "2000",
            # Only include rows that have a hardware_tier set
            "hardware_tier": "neq.",
        }

        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params=params,
            timeout=5,
        )
        resp.raise_for_status()
        rows = resp.json()

        if not rows:
            return {
                "tiers": [],
                "total_submissions": 0,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }

        # Tier labels mapping
        tier_labels = {
            "CLOUD": "Cloud",
            "CONSUMER_HIGH": "Consumer (High)",
            "CONSUMER_MID": "Consumer (Mid)",
            "CONSUMER_LOW": "Consumer (Low)",
            "EDGE": "Edge Device",
        }

        # Aggregate per tier
        tier_data: dict[str, dict] = {}
        for row in rows:
            t = row.get("hardware_tier", "")
            if not t or t not in tier_labels:
                continue
            if t not in tier_data:
                tier_data[t] = {"models": set(), "scores": [], "count": 0}
            tier_data[t]["count"] += 1
            tier_data[t]["models"].add(row["model_name"])
            if row.get("overall_score") is not None:
                tier_data[t]["scores"].append(row["overall_score"])

        tiers = []
        for tier_name in ["CLOUD", "CONSUMER_HIGH", "CONSUMER_MID", "CONSUMER_LOW", "EDGE"]:
            data = tier_data.get(tier_name)
            if data:
                avg = round(sum(data["scores"]) / len(data["scores"]), 1) if data["scores"] else 0
                tiers.append({
                    "tier": tier_name,
                    "label": tier_labels[tier_name],
                    "total_tests": data["count"],
                    "unique_models": len(data["models"]),
                    "avg_score": avg,
                })
            else:
                tiers.append({
                    "tier": tier_name,
                    "label": tier_labels[tier_name],
                    "total_tests": 0,
                    "unique_models": 0,
                    "avg_score": 0,
                })

        total = sum(d["count"] for d in tier_data.values())

        return {
            "tiers": tiers,
            "total_submissions": total,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(f"Failed to get tier distribution: {e}")
        return {"tiers": [], "total_submissions": 0, "last_updated": None}


def get_scores_by_quantization(model_family: str, parameter_size: str) -> dict[str, list[float]]:
    """Get overall_scores grouped by quantization for a model family+size.

    Queries test history where model_config family and parameter_size match,
    then groups the results by quantization level.

    Returns: {"fp16": [85.2, 84.1, ...], "q8_0": [82.3, ...], ...}
    """
    if not is_available():
        return {}

    try:
        params: dict = {
            "select": "overall_score,model_config",
            "order": "timestamp.desc",
            "limit": "500",
            "model_config->>family": f"ilike.*{model_family}*",
            "model_config->>parameter_size": f"ilike.*{parameter_size}*",
        }

        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params=params,
            timeout=5,
        )
        resp.raise_for_status()
        rows = resp.json()

        result: dict[str, list[float]] = {}
        for row in rows:
            mc = row.get("model_config") or {}
            quant = mc.get("quantization", "unknown")
            score = row.get("overall_score")
            if score is not None:
                # Normalize quantization key to lowercase
                quant_key = quant.lower().strip()
                if quant_key not in result:
                    result[quant_key] = []
                result[quant_key].append(score)

        return result
    except Exception as e:
        logger.warning(f"Failed to get scores by quantization: {e}")
        return {}


def get_survey_stats() -> dict:
    """Get hardware survey statistics with percentage distributions.

    Aggregates hardware distribution across all community submissions,
    returning percentages for tier, GPU, RAM, OS, and quantization.
    """
    if not is_available():
        return {"total_submissions": 0}

    try:
        rows = _get_filtered_history(exclude_source="mcp", limit=1000)
        if not rows:
            return {"total_submissions": 0}

        total = len(rows)
        tier_dist: dict[str, int] = {}
        gpu_dist: dict[str, int] = {}
        ram_dist: dict[str, int] = {}
        os_dist: dict[str, int] = {}
        quant_dist: dict[str, int] = {}

        for row in rows:
            hw = row.get("hardware") or {}
            mc = row.get("model_config") or {}
            rt = row.get("runtime") or {}

            # Hardware tier classification
            if hw or rt:
                try:
                    from gauntlet.core.hardware_tiers import classify_from_dicts
                    tier_result = classify_from_dicts(hw, rt, mc)
                    tier_name = tier_result.tier_name
                except Exception:
                    tier_name = "UNKNOWN"
            else:
                tier_name = "UNKNOWN"
            tier_dist[tier_name] = tier_dist.get(tier_name, 0) + 1

            gpu = hw.get("gpu_class", "unknown")
            gpu_dist[gpu] = gpu_dist.get(gpu, 0) + 1

            # Use ram_bucket if available, otherwise derive from ram_total_gb
            ram = hw.get("ram_bucket", "")
            if not ram:
                ram_gb = hw.get("ram_total_gb", 0)
                if isinstance(ram_gb, (int, float)) and ram_gb > 0:
                    if ram_gb < 12:
                        ram = "8gb"
                    elif ram_gb < 24:
                        ram = "16gb"
                    elif ram_gb < 48:
                        ram = "32gb"
                    elif ram_gb < 96:
                        ram = "64gb"
                    else:
                        ram = "128gb+"
                else:
                    ram = "unknown"
            ram_dist[ram] = ram_dist.get(ram, 0) + 1

            osp = hw.get("os_platform", "unknown")
            os_dist[osp] = os_dist.get(osp, 0) + 1

            quant = mc.get("quantization", "unknown")
            quant_dist[quant] = quant_dist.get(quant, 0) + 1

        def _to_pct(dist: dict[str, int]) -> dict[str, float]:
            return {k: round(v / total * 100, 1) for k, v in
                    sorted(dist.items(), key=lambda x: x[1], reverse=True)}

        return {
            "total_submissions": total,
            "tier_distribution": _to_pct(tier_dist),
            "gpu_distribution": _to_pct(gpu_dist),
            "ram_distribution": _to_pct(ram_dist),
            "os_distribution": _to_pct(os_dist),
            "quantization_distribution": _to_pct(quant_dist),
        }
    except Exception as e:
        logger.warning(f"Failed to get survey stats: {e}")
        return {"total_submissions": 0}


def get_model_detail(model_name: str) -> Optional[dict]:
    """Get detailed stats for a single model with per-hardware breakdown."""
    if not is_available():
        return None

    try:
        rows = _get_filtered_history(exclude_source="mcp", limit=500)
        if not rows:
            return None

        model_rows = [r for r in rows if r["model_name"] == model_name]
        if not model_rows:
            return None

        scores = [r["overall_score"] for r in model_rows if r.get("overall_score") is not None]
        trusts = [r["trust_score"] for r in model_rows if r.get("trust_score") is not None]
        grades = [r["grade"] for r in model_rows if r.get("grade")]

        avg_score = sum(scores) / len(scores) if scores else 0
        avg_trust = sum(trusts) / len(trusts) if trusts else 0

        cat_totals: dict[str, float] = {}
        cat_counts: dict[str, int] = {}
        for row in model_rows:
            cats = row.get("category_scores") or {}
            for cat, score in cats.items():
                if isinstance(score, (int, float)):
                    cat_totals[cat] = cat_totals.get(cat, 0) + score
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1

        cat_avgs = {
            cat: round(cat_totals[cat] / cat_counts[cat], 1)
            for cat in cat_totals if cat_counts.get(cat, 0) > 0
        }

        hw_groups: dict[str, dict] = {}
        for row in model_rows:
            hw = row.get("hardware") or {}
            mc = row.get("model_config") or {}

            gpu = hw.get("gpu_class", "unknown")
            gpu_name = hw.get("gpu_name", gpu)
            ram = hw.get("ram_bucket", "unknown")
            quant = mc.get("quantization", "unknown")
            device = hw.get("device_class", "unknown")

            key = f"{gpu}|{ram}|{quant}"
            if key not in hw_groups:
                hw_groups[key] = {
                    "config": f"{gpu_name}, {ram} RAM, {quant}",
                    "gpu_class": gpu,
                    "gpu_name": gpu_name,
                    "ram_bucket": ram,
                    "quantization": quant,
                    "device_class": device,
                    "scores": [],
                    "history": [],
                }

            g = hw_groups[key]
            if row.get("overall_score") is not None:
                g["scores"].append(row["overall_score"])
            if len(g["history"]) < 10:
                g["history"].append({
                    "timestamp": row["timestamp"],
                    "overall_score": row.get("overall_score"),
                })

        breakdown = []
        for key, g in hw_groups.items():
            if g["scores"]:
                breakdown.append({
                    "config": g["config"],
                    "gpu_class": g["gpu_class"],
                    "gpu_name": g["gpu_name"],
                    "ram_bucket": g["ram_bucket"],
                    "quantization": g["quantization"],
                    "device_class": g["device_class"],
                    "avg_score": round(sum(g["scores"]) / len(g["scores"]), 1),
                    "test_count": len(g["scores"]),
                    "history": list(reversed(g["history"])),
                })
        breakdown.sort(key=lambda x: x["avg_score"], reverse=True)

        history = []
        for row in model_rows[:20]:
            history.append({
                "timestamp": row["timestamp"],
                "overall_score": row.get("overall_score"),
                "trust_score": row.get("trust_score"),
            })

        # Aggregate probe-level detail from most recent test that has it.
        # Takes the newest probe results per module across recent runs.
        probe_averages: dict[str, list[dict]] = {}
        for row in model_rows:
            pd = row.get("probe_details")
            if pd and isinstance(pd, dict):
                for mod_name, probes in pd.items():
                    if mod_name not in probe_averages and isinstance(probes, list):
                        probe_averages[mod_name] = probes
                # Break once every category with an average also has probe detail
                if probe_averages.keys() >= cat_avgs.keys():
                    break

        return {
            "name": model_name,
            "overall": {
                "avg_score": round(avg_score, 1),
                "avg_trust": round(avg_trust, 1),
                "grade": grades[0] if grades else "?",
                "test_count": len(model_rows),
            },
            "category_averages": cat_avgs,
            "probe_details": probe_averages if probe_averages else None,
            "hardware_breakdown": breakdown,
            "history": list(reversed(history)),
        }
    except Exception as e:
        logger.warning(f"Failed to get model detail: {e}")
        return None


def get_certification_data(model_name: str) -> Optional[dict]:
    """Get data needed for certification check.

    Queries all submissions for the given model and aggregates:
    - total_submissions (full-suite only, not quick)
    - tiers_tested (distinct hardware_tier values)
    - mean_score (average overall_score)
    - has_critical_safety_failure (any submission with critical safety)

    Returns:
        Dict with certification-relevant aggregates, or None if unavailable.
    """
    if not is_available():
        return None

    try:
        params: dict = {
            "select": "model_name,overall_score,hardware,runtime,category_scores",
            "order": "timestamp.desc",
            "limit": "1000",
            "model_name": f"eq.{model_name}",
        }

        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params=params,
            timeout=5,
        )
        resp.raise_for_status()
        rows = resp.json()

        if not rows:
            return None

        # Compute hardware_tier dynamically from stored JSONB
        from gauntlet.core.hardware_tiers import classify_from_dicts
        for row in rows:
            if not row.get("hardware_tier"):
                try:
                    tier_obj = classify_from_dicts(row.get("hardware", {}), row.get("runtime"))
                    row["hardware_tier"] = tier_obj.tier_name
                except Exception:
                    row["hardware_tier"] = "EDGE"

        # Count all rows as full-suite (quick column may not exist in older data)
        full_rows = [r for r in rows if not r.get("quick", False)]
        if not full_rows:
            full_rows = rows  # Fall back to all rows if none pass the filter
        if not full_rows:
            return {
                "total_submissions": 0,
                "tiers_tested": [],
                "mean_score": 0.0,
                "has_critical_safety_failure": False,
            }

        scores = [
            r["overall_score"] for r in full_rows
            if r.get("overall_score") is not None
        ]
        mean_score = sum(scores) / len(scores) if scores else 0.0

        tiers = set()
        for r in full_rows:
            tier = r.get("hardware_tier", "")
            if tier:
                tiers.add(tier)

        # Check for critical safety failure in category_scores
        # SAFETY_BOUNDARY score of 0 indicates critical safety failure
        has_critical = False
        for r in full_rows:
            cats = r.get("category_scores") or {}
            safety_score = cats.get("SAFETY_BOUNDARY")
            if safety_score is not None and safety_score == 0:
                has_critical = True
                break

        return {
            "total_submissions": len(full_rows),
            "tiers_tested": sorted(tiers),
            "mean_score": round(mean_score, 1),
            "has_critical_safety_failure": has_critical,
        }
    except Exception as e:
        logger.warning(f"Failed to get certification data for {model_name}: {e}")
        return None
