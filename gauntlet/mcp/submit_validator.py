"""Shared validator for community submissions.

Both `/api/submit` (CLI path) and `/mcp` → `_save_mcp_results` (MCP path)
write rows to the same Supabase table. Without a shared validator, the
MCP path bypasses every check the CLI path enforces — meaning anyone
hitting the public `/mcp` endpoint can submit nonsense scores, fake
hardware, or unbounded payloads.

This module lives here (not in api/) so it can be imported from both
the API handler AND the MCP server's `_save_mcp_results`. Imports
nothing from FastMCP or starlette — pure validation logic.

Returns None on success, or a human-readable error string on failure.
The caller decides whether to log, return 400, or skip the write.
"""

from __future__ import annotations

import hashlib
import time
from typing import Optional


# ---------------------------------------------------------------------------
# Constraints (mirrored from the original api/index.py:submit_handler)
# ---------------------------------------------------------------------------

MIN_MODEL_NAME_LEN = 2
MAX_MODEL_NAME_LEN = 100
MIN_PROBES = 4
MIN_CATEGORIES = 2
SCORE_CONSISTENCY_DELTA = 40.0   # max |overall - cat_avg|
PROBE_DETAILS_MAX_MODULES = 30
PROBE_DETAILS_MAX_PROBES = 200
PROBE_DETAILS_REASON_MAX = 500


# Module-local dedup window: simple in-memory dict, same approach as the
# rate limiter in api/index.py. The MCP path runs in long-lived processes
# so this works as long as restarts are rare.
_recent_dedup: dict[str, float] = {}
_DEDUP_WINDOW_SEC = 60.0


def _check_dedup(model_name: str, overall_score: float, hw: Optional[dict]) -> bool:
    """Return True if this looks like a duplicate. False = OK."""
    hw_key = ""
    if hw:
        hw_key = f"{hw.get('cpu_arch','')}-{hw.get('gpu_class','')}-{hw.get('ram_total_gb','')}"
    key = f"{model_name}:{overall_score:.1f}:{hw_key}"
    h = hashlib.md5(key.encode()).hexdigest()
    now = time.time()

    # Periodic cleanup to keep the dict bounded
    if len(_recent_dedup) > 500:
        expired = [k for k, t in _recent_dedup.items() if now - t > _DEDUP_WINDOW_SEC]
        for k in expired:
            del _recent_dedup[k]

    if h in _recent_dedup and now - _recent_dedup[h] < _DEDUP_WINDOW_SEC:
        return True
    _recent_dedup[h] = now
    return False


def validate_submission(
    payload: dict,
    *,
    valid_categories: Optional[set[str]] = None,
    valid_hardware_tiers: Optional[set[str]] = None,
    check_dedup: bool = True,
) -> Optional[str]:
    """Validate a submission payload. Returns None on success, error string on failure.

    Args:
        payload: the submission dict (model_name, overall_score, etc.)
        valid_categories: optional allowlist of category names. If None, the
            category-name check is skipped (caller may not have access to the
            module registry).
        valid_hardware_tiers: optional allowlist for `hardware_tier` /
            `attestation.hardware_tier`. If None, tier values are accepted as-is.
        check_dedup: enable in-process duplicate detection.
    """
    # ---- required fields ----
    model_name = payload.get("model_name")
    overall_score = payload.get("overall_score")
    if not model_name:
        return "Missing required field: model_name"
    if overall_score is None:
        return "Missing required field: overall_score"

    # ---- types & ranges ----
    if not isinstance(overall_score, (int, float)):
        return "overall_score must be a number"
    if overall_score < 0 or overall_score > 100:
        return f"overall_score out of range (got {overall_score}, expected 0-100)"

    if not isinstance(model_name, str):
        return "model_name must be a string"
    if len(model_name) < MIN_MODEL_NAME_LEN or len(model_name) > MAX_MODEL_NAME_LEN:
        return (
            f"model_name length out of range "
            f"(got {len(model_name)}, expected {MIN_MODEL_NAME_LEN}-{MAX_MODEL_NAME_LEN})"
        )

    # ---- category scores ----
    cat_scores = payload.get("category_scores", {})
    if not isinstance(cat_scores, dict):
        return "category_scores must be a dict"
    # Strip private / synthetic keys before counting (matches submit_handler behavior)
    real_cats = {k: v for k, v in cat_scores.items() if not k.startswith("_")}
    if len(real_cats) < MIN_CATEGORIES:
        return f"Insufficient category data (got {len(real_cats)}, need ≥{MIN_CATEGORIES})"
    if valid_categories is not None:
        unknown = set(real_cats) - valid_categories
        if unknown:
            return f"Unknown categories: {', '.join(sorted(unknown))}"
    for k, v in real_cats.items():
        if not isinstance(v, (int, float)):
            return f"Category score must be numeric (got {type(v).__name__} for {k})"
        if v < 0 or v > 100:
            return f"Category score out of range for {k}: {v}"

    # ---- score consistency ----
    if real_cats:
        cat_avg = sum(real_cats.values()) / len(real_cats)
        if abs(overall_score - cat_avg) > SCORE_CONSISTENCY_DELTA:
            return (
                f"Score inconsistency: overall {overall_score} vs "
                f"category avg {cat_avg:.1f} (delta {abs(overall_score - cat_avg):.1f} > "
                f"{SCORE_CONSISTENCY_DELTA})"
            )

    # ---- probe count ----
    total_probes = payload.get("total_probes", 0)
    if not isinstance(total_probes, int) or total_probes < MIN_PROBES:
        return f"total_probes must be ≥{MIN_PROBES} (got {total_probes})"

    # ---- attestation ----
    attestation = payload.get("attestation")
    if attestation is not None:
        if not isinstance(attestation, dict):
            return "attestation must be a dict"
        if not attestation.get("gauntlet_version"):
            return "attestation missing gauntlet_version"
        att_tier = attestation.get("hardware_tier", "")
        if not isinstance(att_tier, str):
            return "attestation.hardware_tier must be a string"
        if valid_hardware_tiers is not None and att_tier not in valid_hardware_tiers:
            return f"Invalid attestation hardware_tier: {att_tier!r}"

    # ---- probe_details size cap ----
    probe_details = payload.get("probe_details")
    if probe_details is not None:
        if not isinstance(probe_details, dict) or len(probe_details) > PROBE_DETAILS_MAX_MODULES:
            return f"probe_details too large (max {PROBE_DETAILS_MAX_MODULES} modules)"
        for mod, probes in probe_details.items():
            if not isinstance(mod, str) or len(mod) > 64:
                return f"probe_details module name invalid: {mod!r}"
            if not isinstance(probes, list) or len(probes) > PROBE_DETAILS_MAX_PROBES:
                return f"probe_details for {mod} too large (max {PROBE_DETAILS_MAX_PROBES})"

    # ---- dedup ----
    if check_dedup:
        if _check_dedup(model_name, overall_score, payload.get("hardware")):
            return f"Duplicate submission within {int(_DEDUP_WINDOW_SEC)}s window"

    return None  # OK
