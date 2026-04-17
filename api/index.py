"""Vercel serverless entry point for Gauntlet MCP server + REST API.

Exposes:
  /mcp                      - MCP streamable-http transport
  /api/leaderboard          - Public leaderboard JSON (comparative ratings)
  /api/leaderboard/history  - Test history + aggregated stats for graphs
  /api/leaderboard/tier     - Hardware-stratified leaderboard per tier
  /api/leaderboard/tiers    - Aggregate overview across all hardware tiers
  /api/predict               - Predict model performance on untested hardware
  /api/recommend             - Recommend hardware tier for a target score
  /api/degradation           - Quantization degradation curves per model family
  /api/survey                - Community hardware distribution survey
  /api/badge                 - Embeddable SVG badges (shields.io style)
  /api/certification         - Model certification status (gold/silver/bronze)
  /api/health               - Health check endpoint
"""

import hashlib
import hmac
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from gauntlet.mcp.server import mcp

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

# Minimum CLI version allowed to submit (reject older broken versions)
MIN_CLI_VERSION = "1.3.5"

# Valid category names: auto-derived from the module registry + fixed
# non-module categories (benchmark/compare + health check domains).
# This means adding a new module NEVER requires updating this file.
def _build_valid_categories() -> set[str]:
    """Auto-discover module names from the registry + add fixed categories."""
    cats: set[str] = set()
    try:
        from gauntlet.core.module_runner import load_all_modules, list_modules
        load_all_modules()
        cats = {m.name for m in list_modules()}
    except Exception:
        # Fallback if import fails (cold start edge case)
        cats = {
            "AMBIGUITY_HONESTY", "SYCOPHANCY_TRAP", "INSTRUCTION_ADHERENCE",
            "CONSISTENCY_DRIFT", "SAFETY_NUANCE", "HALLUCINATION_PROBE",
            "CONTEXT_FIDELITY", "REFUSAL_CALIBRATION", "CONTAMINATION_CHECK",
            "TEMPORAL_COHERENCE", "INSTRUCTION_DECAY", "SYCOPHANCY_GRADIENT",
            "CONFIDENCE_CALIBRATION", "ANCHORING_BIAS", "PROMPT_INJECTION",
            "LOGICAL_CONSISTENCY", "FRAMING_EFFECT", "PERPLEXITY_BASELINE",
            "LAYER_SENSITIVITY",
        }
    # Non-module categories that appear in submissions (benchmark/compare + health check)
    cats |= {"speed", "quality", "responsiveness", "overall"}
    cats |= {"writing", "code", "reasoning", "summarization", "data_analysis", "creative", "regression_anchor"}
    return cats

VALID_CATEGORIES = _build_valid_categories()

# HMAC signing key (shared with CLI, not truly secret but stops casual abuse)
_SUBMIT_KEY = os.environ.get("GAUNTLET_SUBMIT_KEY", "gauntlet-community-2026")

# Rate limiting: per-IP tracking (in-memory, resets on cold start)
_rate_limits: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60.0   # seconds
_RATE_MAX = 10         # max submissions per window per IP

# Duplicate detection: recent submission hashes
_recent_submissions: dict[str, float] = {}
_DEDUP_WINDOW = 60.0   # seconds

# Allow all hosts for public deployment (default only allows localhost)
mcp.settings.transport_security.enable_dns_rebinding_protection = False
mcp.settings.stateless_http = True

_mcp_app = mcp.streamable_http_app()


# ---------------------------------------------------------------------------
# REST API routes
# ---------------------------------------------------------------------------

# Read-only endpoints: open to all origins (public data)
CORS_HEADERS_READ = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "public, max-age=30, s-maxage=60",
}

# Write endpoints: restrict to CLI user-agent (not browser-exploitable)
CORS_HEADERS_WRITE = {
    "Access-Control-Allow-Origin": "https://basaltlabs.app",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Gauntlet-Signature",
}

# Backward compat alias — existing code references this
CORS_HEADERS = CORS_HEADERS_READ


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple[int, ...]:
    """Parse semver string into comparable tuple."""
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is within rate limits."""
    now = time.time()
    # Prune old entries
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < _RATE_WINDOW]
    if len(_rate_limits[ip]) >= _RATE_MAX:
        return False
    _rate_limits[ip].append(now)
    return True


def _check_duplicate(model_name: str, overall_score: float, hw: Optional[dict]) -> bool:
    """Return True if this looks like a duplicate submission. False = OK."""
    # Build a fingerprint of the submission
    hw_key = ""
    if hw:
        hw_key = f"{hw.get('cpu_arch', '')}-{hw.get('gpu_class', '')}-{hw.get('ram_total_gb', '')}"
    dedup_key = f"{model_name}:{overall_score:.1f}:{hw_key}"
    dedup_hash = hashlib.md5(dedup_key.encode()).hexdigest()

    now = time.time()
    # Prune old entries (every 100 checks)
    if len(_recent_submissions) > 500:
        expired = [k for k, t in _recent_submissions.items() if now - t > _DEDUP_WINDOW]
        for k in expired:
            del _recent_submissions[k]

    if dedup_hash in _recent_submissions:
        if now - _recent_submissions[dedup_hash] < _DEDUP_WINDOW:
            return True  # duplicate
    _recent_submissions[dedup_hash] = now
    return False  # not a duplicate


def _verify_signature(body_bytes: bytes, signature: Optional[str]) -> bool:
    """Verify HMAC-SHA256 signature from CLI. Returns True if valid or no key configured."""
    if not signature:
        return False
    expected = hmac.new(_SUBMIT_KEY.encode(), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def leaderboard_handler(request: Request) -> Response:
    """GET /api/leaderboard — public leaderboard JSON."""
    from gauntlet.mcp.leaderboard_store import get_leaderboard, is_available

    if not is_available():
        return JSONResponse(
            {"models": [], "note": "No models ranked yet. Run gauntlet compare to start."},
            headers=CORS_HEADERS,
        )

    models = get_leaderboard()
    return JSONResponse(
        {"models": models, "total": len(models), "updated_at": datetime.now(timezone.utc).isoformat()},
        headers=CORS_HEADERS,
    )


async def history_handler(request: Request) -> Response:
    """GET /api/leaderboard/history — aggregated stats with optional filters.

    Query params:
        gpu_class: apple_silicon, nvidia, amd, none
        quantization: Q4_K_M, Q8_0, fp16, etc.
        parameter_size: 7b, 14b, 35b
        provider: ollama, openai, anthropic
        model_family: llama, qwen, gemma
        os_platform: darwin, linux, windows
        min_tests: minimum test count to include (default 1)
    """
    from gauntlet.mcp.history_store import get_aggregated_stats, is_available

    if not is_available():
        return JSONResponse(
            {"models": [], "note": "No test history yet."},
            headers=CORS_HEADERS,
        )

    # Extract filter params from query string
    params = request.query_params
    min_tests = 1
    try:
        min_tests = int(params.get("min_tests", "1"))
    except ValueError:
        pass

    stats = get_aggregated_stats(
        gpu_class=params.get("gpu_class"),
        quantization=params.get("quantization"),
        parameter_size=params.get("parameter_size"),
        provider=params.get("provider"),
        model_family=params.get("model_family"),
        os_platform=params.get("os_platform"),
        source=params.get("source"),
        exclude_source=params.get("exclude_source"),
        ram_bucket=params.get("ram_bucket"),
        vram_bucket=params.get("vram_bucket"),
        device_class=params.get("device_class"),
        gpu_name=params.get("gpu_name"),
        min_tests=min_tests,
    )

    _FILTER_KEYS = {
        "gpu_class", "quantization", "parameter_size", "provider",
        "model_family", "os_platform", "min_tests", "source",
        "exclude_source", "ram_bucket", "vram_bucket", "device_class", "gpu_name",
    }
    active_filters = {k: v for k, v in params.items() if k in _FILTER_KEYS}

    return JSONResponse(
        {
            "models": stats,
            "total": len(stats),
            "filters": active_filters,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        headers=CORS_HEADERS,
    )


async def submit_handler(request: Request) -> Response:
    """POST /api/submit -- accept community test results from CLI users.

    Internal API used by the gauntlet CLI. Not documented publicly.
    12-point validation prevents fake, duplicate, and abusive submissions.
    """
    # Write endpoint uses restricted CORS (basaltlabs.app only, not *)
    CORS_HEADERS = CORS_HEADERS_WRITE  # noqa: F841 — intentional shadow

    # ── 1. Rate limiting (per IP) ────────────────────────────────────────
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    if not _check_rate_limit(client_ip):
        return JSONResponse(
            {"error": "Rate limit exceeded. Max 10 submissions per minute."},
            status_code=429, headers=CORS_HEADERS,
        )

    # ── Parse body ───────────────────────────────────────────────────────
    try:
        body_bytes = await request.body()
        import json as _json
        body = _json.loads(body_bytes)
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400, headers=CORS_HEADERS)

    # ── 2. Signature verification (HMAC-SHA256) ──────────────────────────
    signature = request.headers.get("x-gauntlet-signature")
    if not _verify_signature(body_bytes, signature):
        return JSONResponse(
            {"error": "Invalid or missing signature"},
            status_code=403, headers=CORS_HEADERS,
        )

    # ── 3. Version pinning ───────────────────────────────────────────────
    cli_version = body.get("cli_version", "")
    if not cli_version or _parse_version(cli_version) < _parse_version(MIN_CLI_VERSION):
        return JSONResponse(
            {"error": f"CLI version too old. Minimum: {MIN_CLI_VERSION}. Run: pipx upgrade gauntlet-cli"},
            status_code=400, headers=CORS_HEADERS,
        )

    # ── Validate required fields ─────────────────────────────────────────
    model_name = body.get("model_name")
    overall_score = body.get("overall_score")
    if not model_name or overall_score is None:
        return JSONResponse(
            {"error": "Missing required fields: model_name, overall_score"},
            status_code=400, headers=CORS_HEADERS,
        )

    # ── 4. Score range check ─────────────────────────────────────────────
    if not isinstance(overall_score, (int, float)) or overall_score < 0 or overall_score > 100:
        return JSONResponse({"error": "Invalid score range"}, status_code=400, headers=CORS_HEADERS)

    # ── 5. Model name length check ───────────────────────────────────────
    if len(model_name) > 100 or len(model_name) < 2:
        return JSONResponse({"error": "Invalid model name"}, status_code=400, headers=CORS_HEADERS)

    # ── 6. Category score validation ─────────────────────────────────────
    cat_scores = body.get("category_scores", {})
    if not isinstance(cat_scores, dict) or len(cat_scores) < 2:
        return JSONResponse({"error": "Insufficient category data"}, status_code=400, headers=CORS_HEADERS)

    # 6a. Only accept known category names
    unknown_cats = set(cat_scores.keys()) - VALID_CATEGORIES
    if unknown_cats:
        return JSONResponse(
            {"error": f"Unknown categories: {', '.join(sorted(unknown_cats))}"},
            status_code=400, headers=CORS_HEADERS,
        )

    # 6b. All category scores must be valid numbers 0-100
    for cat_name, cat_val in cat_scores.items():
        if not isinstance(cat_val, (int, float)) or cat_val < 0 or cat_val > 100:
            return JSONResponse(
                {"error": f"Invalid score for category {cat_name}"},
                status_code=400, headers=CORS_HEADERS,
            )

    # ── 7. Score consistency check ───────────────────────────────────────
    # Overall score should be roughly consistent with category averages
    if cat_scores:
        cat_avg = sum(cat_scores.values()) / len(cat_scores)
        # Allow 40-point tolerance (profile weights differ 0.3-1.0x across modules,
        # so weighted overall can diverge substantially from unweighted category mean)
        if abs(overall_score - cat_avg) > 40:
            return JSONResponse(
                {"error": "Score inconsistency: overall score doesn't match category averages"},
                status_code=400, headers=CORS_HEADERS,
            )

    # ── 8. Probe count sanity ────────────────────────────────────────────
    total_probes = body.get("total_probes", 0)
    if not isinstance(total_probes, int) or total_probes < 4:
        return JSONResponse({"error": "Invalid probe count"}, status_code=400, headers=CORS_HEADERS)

    # ── 9. Hardware fingerprint required ─────────────────────────────────
    hw = body.get("hardware")
    rt = body.get("runtime")
    if not hw and not rt:
        return JSONResponse({"error": "Missing system fingerprint"}, status_code=400, headers=CORS_HEADERS)

    # ── 10. Duplicate detection ──────────────────────────────────────────
    if _check_duplicate(model_name, overall_score, hw):
        return JSONResponse(
            {"error": "Duplicate submission detected. Please wait before resubmitting."},
            status_code=409, headers=CORS_HEADERS,
        )

    # ── 11a. Attestation validation (optional, backward compatible) ──────
    VALID_HARDWARE_TIERS = {"CLOUD", "CONSUMER_HIGH", "CONSUMER_MID", "CONSUMER_LOW", "EDGE", ""}
    attestation = body.get("attestation")
    if attestation is not None:
        if not isinstance(attestation, dict):
            return JSONResponse({"error": "Invalid attestation format"}, status_code=400, headers=CORS_HEADERS)
        att_version = attestation.get("gauntlet_version", "")
        if not isinstance(att_version, str) or not att_version:
            return JSONResponse({"error": "Attestation missing gauntlet_version"}, status_code=400, headers=CORS_HEADERS)
        att_tier = attestation.get("hardware_tier", "")
        if not isinstance(att_tier, str) or att_tier not in VALID_HARDWARE_TIERS:
            return JSONResponse(
                {"error": f"Invalid attestation hardware_tier: {att_tier}"},
                status_code=400, headers=CORS_HEADERS,
            )

    # ── 11b. probe_details size + shape validation ─────────────────────
    probe_details = body.get("probe_details")
    if probe_details is not None:
        if not isinstance(probe_details, dict) or len(probe_details) > 30:
            return JSONResponse({"error": "Invalid probe_details"}, status_code=400, headers=CORS_HEADERS)
        for mod_key, mod_probes in probe_details.items():
            if not isinstance(mod_key, str) or len(mod_key) > 64:
                return JSONResponse({"error": "Invalid probe_details module name"}, status_code=400, headers=CORS_HEADERS)
            if not isinstance(mod_probes, list) or len(mod_probes) > 200:
                return JSONResponse({"error": f"Too many probes in {mod_key}"}, status_code=400, headers=CORS_HEADERS)
            for p in mod_probes:
                if not isinstance(p, dict):
                    return JSONResponse({"error": "Invalid probe entry"}, status_code=400, headers=CORS_HEADERS)
                reason_val = p.get("reason", "")
                if isinstance(reason_val, str) and len(reason_val) > 500:
                    p["reason"] = reason_val[:500]  # Truncate rather than reject

    # ── Store result ─────────────────────────────────────────────────────
    from gauntlet.mcp.history_store import record_test_result, is_available
    if not is_available():
        return JSONResponse(
            {"error": "Storage not configured"}, status_code=503, headers=CORS_HEADERS,
        )

    # Reconstruct fingerprint from submitted hardware/runtime/model_config
    fingerprint = None
    mc = body.get("model_config")
    if hw or rt or mc:
        from gauntlet.core.system_info import SystemFingerprint
        fingerprint = SystemFingerprint(
            cpu_arch=(hw or {}).get("cpu_arch", "unknown"),
            cpu_cores=(hw or {}).get("cpu_cores", 0),
            ram_total_gb=(hw or {}).get("ram_total_gb", 0),
            gpu_class=(hw or {}).get("gpu_class", "unknown"),
            os_platform=(hw or {}).get("os_platform", "unknown"),
            python_version=(rt or {}).get("python_version", ""),
            os_version=(rt or {}).get("os_version", ""),
            provider=(rt or {}).get("provider", "unknown"),
            provider_version=(rt or {}).get("provider_version", ""),
            model_family=(mc or {}).get("family", "unknown"),
            model_parameter_size=(mc or {}).get("parameter_size", ""),
            quantization=(mc or {}).get("quantization", "unknown"),
            model_format=(mc or {}).get("format", "unknown"),
            model_size_gb=(mc or {}).get("size_gb", 0),
        )

    # Inject raw perplexity into category_scores JSONB so it's stored
    # alongside the behavioral scores without needing a schema migration.
    # The degradation API reads it back as "_perplexity_raw".
    cat_scores = dict(body.get("category_scores", {}))
    raw_ppl = body.get("perplexity")
    if raw_ppl is not None:
        cat_scores["_perplexity_raw"] = raw_ppl

    try:
        record_test_result(
            model_name=model_name,
            overall_score=body.get("overall_score", 0),
            trust_score=body.get("trust_score", 0),
            grade=body.get("grade", "?"),
            category_scores=cat_scores,
            total_probes=body.get("total_probes", 0),
            passed_probes=body.get("passed_probes", 0),
            source=body.get("source", "cli"),
            quick=body.get("quick", False),
            fingerprint=fingerprint,
            probe_details=body.get("probe_details"),
            attestation=body.get("attestation"),
            hardware_tier=body.get("hardware_tier", ""),
            suite_type=body.get("attestation", {}).get("suite_type", "full"),
        )
    except Exception as e:
        return JSONResponse(
            {"status": "ok", "storage_warning": str(e)}, headers=CORS_HEADERS,
        )

    return JSONResponse({"status": "ok"}, headers=CORS_HEADERS)


async def stats_handler(request: Request) -> Response:
    """GET /api/leaderboard/stats -- community aggregate statistics."""
    from gauntlet.mcp.history_store import get_community_stats, is_available

    if not is_available():
        return JSONResponse({"total_tests": 0}, headers=CORS_HEADERS)

    stats = get_community_stats()
    return JSONResponse(stats, headers=CORS_HEADERS)


async def tier_leaderboard_handler(request: Request) -> Response:
    """GET /api/leaderboard/tier?tier=CONSUMER_MID — ranked models within a hardware tier."""
    from gauntlet.mcp.history_store import get_tier_leaderboard, is_available

    VALID_TIERS = {"CLOUD", "CONSUMER_HIGH", "CONSUMER_MID", "CONSUMER_LOW", "EDGE"}

    tier = request.query_params.get("tier", "")
    if not tier:
        return JSONResponse(
            {"error": "Missing required parameter: tier"},
            status_code=400, headers=CORS_HEADERS,
        )
    if tier not in VALID_TIERS:
        return JSONResponse(
            {"error": f"Invalid tier: {tier}. Must be one of: {', '.join(sorted(VALID_TIERS))}"},
            status_code=400, headers=CORS_HEADERS,
        )

    if not is_available():
        return JSONResponse(
            {"error": "Storage not configured"}, status_code=503, headers=CORS_HEADERS,
        )

    limit = 50
    try:
        limit = int(request.query_params.get("limit", "50"))
        limit = max(1, min(limit, 200))
    except ValueError:
        pass

    models = get_tier_leaderboard(tier, limit=limit)
    return JSONResponse(
        {
            "tier": tier,
            "models": models,
            "total": len(models),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        headers=CORS_HEADERS,
    )


async def tiers_overview_handler(request: Request) -> Response:
    """GET /api/leaderboard/tiers — aggregate stats per hardware tier."""
    from gauntlet.mcp.history_store import get_tier_distribution, is_available

    if not is_available():
        return JSONResponse(
            {"tiers": [], "total_submissions": 0, "note": "Storage not configured"},
            headers=CORS_HEADERS,
        )

    distribution = get_tier_distribution()
    return JSONResponse(distribution, headers=CORS_HEADERS)


async def model_detail_handler(request: Request) -> Response:
    """GET /api/leaderboard/model?name=qwen3.5:4b -- per-hardware breakdown for one model."""
    from gauntlet.mcp.history_store import get_model_detail, is_available

    model_name = request.query_params.get("name", "")
    if not model_name:
        return JSONResponse({"error": "Missing name parameter"}, status_code=400, headers=CORS_HEADERS)

    if not is_available():
        return JSONResponse({"error": "Storage not configured"}, status_code=503, headers=CORS_HEADERS)

    detail = get_model_detail(model_name)
    if detail is None:
        return JSONResponse({"error": f"No data for model: {model_name}"}, status_code=404, headers=CORS_HEADERS)

    return JSONResponse(detail, headers=CORS_HEADERS)


async def degradation_handler(request: Request) -> Response:
    """GET /api/degradation?model_family=llama&parameter_size=7b

    Returns quantization degradation curves for a model family + size.
    Groups scores by quantization level, computes statistics and
    pairwise score drops using compute_degradation().
    """
    from gauntlet.mcp.history_store import get_scores_by_quantization, is_available
    from gauntlet.core.statistics import compute_statistics, compute_degradation

    model_family = request.query_params.get("model_family", "")
    parameter_size = request.query_params.get("parameter_size", "")

    if not model_family or not parameter_size:
        return JSONResponse(
            {"error": "Missing required parameters: model_family and parameter_size"},
            status_code=400, headers=CORS_HEADERS,
        )

    if not is_available():
        return JSONResponse(
            {"error": "Storage not configured"}, status_code=503, headers=CORS_HEADERS,
        )

    scores_by_quant, perplexity_by_quant = get_scores_by_quantization(model_family, parameter_size)
    if not scores_by_quant:
        return JSONResponse(
            {"error": f"No data for model_family={model_family}, parameter_size={parameter_size}"},
            status_code=404, headers=CORS_HEADERS,
        )

    # Compute per-level statistics (behavioral scores)
    levels = {}
    for quant, scores in scores_by_quant.items():
        stats = compute_statistics(scores)
        if stats is not None:
            level_data = {
                "mean": stats.mean,
                "sample_size": stats.sample_size,
                "ci_lower": stats.ci_lower,
                "ci_upper": stats.ci_upper,
            }
            # Include perplexity statistics if V2 data is available
            ppl_values = perplexity_by_quant.get(quant, [])
            if ppl_values:
                ppl_stats = compute_statistics(ppl_values)
                if ppl_stats is not None:
                    level_data["perplexity_mean"] = round(ppl_stats.mean, 2)
                    level_data["perplexity_n"] = ppl_stats.sample_size
            levels[quant] = level_data

    # Compute degradation drops
    degradation = compute_degradation(scores_by_quant)

    return JSONResponse(
        {
            "model_family": model_family,
            "parameter_size": parameter_size,
            "levels": levels,
            "degradation": degradation,
            "has_perplexity": any(
                "perplexity_mean" in v for v in levels.values()
            ),
        },
        headers=CORS_HEADERS,
    )


async def survey_handler(request: Request) -> Response:
    """GET /api/survey — community hardware distribution survey.

    Aggregates hardware distribution across all submissions and
    returns percentage breakdowns for tiers, GPUs, RAM, OS, and quantization.
    """
    from gauntlet.mcp.history_store import get_survey_stats, is_available

    if not is_available():
        return JSONResponse({"total_submissions": 0}, headers=CORS_HEADERS)

    stats = get_survey_stats()
    return JSONResponse(stats, headers=CORS_HEADERS)


# ---------------------------------------------------------------------------
# Badge SVG generation
# ---------------------------------------------------------------------------

# Grade-to-color mapping for badges
_BADGE_COLORS = {
    "A": "#4c1",
    "B": "#a4a61d",
    "C": "#dfb317",
    "D": "#fe7d37",
    "F": "#e05d44",
}

_BADGE_GRAY = "#9f9f9f"


def _generate_badge_svg(label: str, value: str, color: str) -> str:
    """Generate a shields.io-style SVG badge."""
    label_width = len(label) * 6.5 + 10
    value_width = len(value) * 6.5 + 10
    total_width = label_width + value_width
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="a"><rect width="{total_width}" height="20" rx="3"/></clipPath>
  <g clip-path="url(#a)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#b)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,sans-serif" font-size="11">
    <text x="{label_width/2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width/2}" y="14">{label}</text>
    <text x="{label_width + value_width/2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{label_width + value_width/2}" y="14">{value}</text>
  </g>
</svg>'''


async def badge_handler(request: Request) -> Response:
    """GET /api/badge?model=qwen2.5:14b&tier=CONSUMER_MID&format=svg

    Returns an SVG badge showing the model's grade on the specified tier.
    Designed for embedding in READMEs and documentation.
    """
    model = request.query_params.get("model", "")
    tier = request.query_params.get("tier", "")

    badge_headers = {
        **CORS_HEADERS,
        "Content-Type": "image/svg+xml",
        "Cache-Control": "public, max-age=3600",
    }

    if not model:
        svg = _generate_badge_svg("gauntlet", "no data", _BADGE_GRAY)
        return Response(svg, media_type="image/svg+xml", headers=badge_headers)

    # Look up model data
    from gauntlet.mcp.history_store import is_available
    if not is_available():
        svg = _generate_badge_svg("gauntlet", "no data", _BADGE_GRAY)
        return Response(svg, media_type="image/svg+xml", headers=badge_headers)

    try:
        if tier:
            # Tier-specific lookup
            from gauntlet.mcp.history_store import get_tier_leaderboard
            models = get_tier_leaderboard(tier, limit=200)
            match = next((m for m in models if m["model_name"] == model), None)
            if match:
                grade = match.get("grade", "?")
                score = match.get("mean", 0)
            else:
                grade = None
                score = None
        else:
            # Global lookup
            from gauntlet.mcp.history_store import get_model_detail
            detail = get_model_detail(model)
            if detail:
                grade = detail.get("overall", {}).get("grade", "?")
                score = detail.get("overall", {}).get("avg_score", 0)
            else:
                grade = None
                score = None
    except Exception:
        grade = None
        score = None

    if grade is None:
        svg = _generate_badge_svg("gauntlet", "no data", _BADGE_GRAY)
        return Response(svg, media_type="image/svg+xml", headers=badge_headers)

    # Build label and value
    label = "gauntlet"
    # Use just the first letter of grade for color mapping
    grade_letter = grade[0].upper() if grade and grade[0].upper() in _BADGE_COLORS else "F"
    color = _BADGE_COLORS.get(grade_letter, _BADGE_GRAY)

    value = f"{grade} ({score:.1f})" if isinstance(score, (int, float)) and score > 0 else grade
    svg = _generate_badge_svg(label, value, color)
    return Response(svg, media_type="image/svg+xml", headers=badge_headers)


async def predict_handler(request: Request) -> Response:
    """GET /api/predict?model=qwen2.5:14b&tier=CONSUMER_MID

    Predict model performance on a hardware tier using collaborative filtering.
    Builds a score matrix from community history data and finds similar models
    to interpolate expected scores.
    """
    from gauntlet.mcp.history_store import is_available
    from gauntlet.core.prediction import (
        PerformancePredictor,
        build_score_matrix_from_history,
    )

    model = request.query_params.get("model", "")
    tier = request.query_params.get("tier", "")

    if not model:
        return JSONResponse(
            {"error": "Missing required parameter: model"},
            status_code=400, headers=CORS_HEADERS,
        )
    if not tier:
        return JSONResponse(
            {"error": "Missing required parameter: tier"},
            status_code=400, headers=CORS_HEADERS,
        )

    VALID_TIERS = {"CLOUD", "CONSUMER_HIGH", "CONSUMER_MID", "CONSUMER_LOW", "EDGE"}
    if tier not in VALID_TIERS:
        return JSONResponse(
            {"error": f"Invalid tier: {tier}. Must be one of: {', '.join(sorted(VALID_TIERS))}"},
            status_code=400, headers=CORS_HEADERS,
        )

    if not is_available():
        return JSONResponse(
            {"error": "Storage not configured"}, status_code=503, headers=CORS_HEADERS,
        )

    # Fetch history rows with hardware_tier data
    import httpx
    from gauntlet.mcp.history_store import _table_url, _headers
    try:
        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params={
                "select": "model_name,overall_score,hardware,runtime",
                "order": "timestamp.desc",
                "limit": "2000",
            },
            timeout=5,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to fetch history: {str(e)}"},
            status_code=503, headers=CORS_HEADERS,
        )

    # Compute hardware_tier dynamically for rows that don't have it stored
    from gauntlet.core.hardware_tiers import classify_from_dicts
    for row in rows:
        if not row.get("hardware_tier"):
            try:
                tier_obj = classify_from_dicts(row.get("hardware", {}), row.get("runtime"))
                row["hardware_tier"] = tier_obj.tier_name
            except Exception:
                row["hardware_tier"] = "EDGE"

    matrix = build_score_matrix_from_history(rows)
    predictor = PerformancePredictor(matrix)
    result = predictor.predict(model, tier)

    return JSONResponse(
        {
            "model": model,
            "tier": tier,
            "predicted_score": result.predicted_score,
            "confidence": result.confidence,
            "basis": result.basis,
            "similar_models": result.similar_models,
            "sample_size": result.sample_size,
            "notes": result.notes,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        headers=CORS_HEADERS,
    )


async def recommend_handler(request: Request) -> Response:
    """GET /api/recommend?model=qwen2.5:14b&min_score=75

    Recommend minimum and optimal hardware tiers for a model to achieve
    a target score threshold. Uses collaborative filtering predictions
    across all hardware tiers.
    """
    from gauntlet.mcp.history_store import is_available
    from gauntlet.core.prediction import (
        PerformancePredictor,
        build_score_matrix_from_history,
    )

    model = request.query_params.get("model", "")
    if not model:
        return JSONResponse(
            {"error": "Missing required parameter: model"},
            status_code=400, headers=CORS_HEADERS,
        )

    min_score = 75.0
    try:
        min_score = float(request.query_params.get("min_score", "75"))
    except ValueError:
        pass

    if min_score < 0 or min_score > 100:
        return JSONResponse(
            {"error": "min_score must be between 0 and 100"},
            status_code=400, headers=CORS_HEADERS,
        )

    if not is_available():
        return JSONResponse(
            {"error": "Storage not configured"}, status_code=503, headers=CORS_HEADERS,
        )

    # Fetch history rows
    import httpx
    from gauntlet.mcp.history_store import _table_url, _headers
    try:
        resp = httpx.get(
            _table_url(),
            headers={**_headers(), "Prefer": "return=representation"},
            params={
                "select": "model_name,overall_score,hardware,runtime",
                "order": "timestamp.desc",
                "limit": "2000",
            },
            timeout=5,
        )
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to fetch history: {str(e)}"},
            status_code=503, headers=CORS_HEADERS,
        )

    # Compute hardware_tier dynamically
    from gauntlet.core.hardware_tiers import classify_from_dicts
    for row in rows:
        if not row.get("hardware_tier"):
            try:
                tier_obj = classify_from_dicts(row.get("hardware", {}), row.get("runtime"))
                row["hardware_tier"] = tier_obj.tier_name
            except Exception:
                row["hardware_tier"] = "EDGE"

    matrix = build_score_matrix_from_history(rows)
    predictor = PerformancePredictor(matrix)
    recommendation = predictor.recommended_tier(model, min_score=min_score)

    return JSONResponse(
        {
            "model": model,
            "minimum_tier": recommendation.get("minimum_tier"),
            "recommended_tier": recommendation.get("recommended_tier"),
            "min_score_target": recommendation.get("min_score_target"),
            "predictions": recommendation.get("predictions", {}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        headers=CORS_HEADERS,
    )


async def certification_handler(request: Request) -> Response:
    """GET /api/certification?model=qwen2.5:14b — certification status for a model.

    Certification levels:
    - Gold: mean_score >= 90, >= 20 submissions, >= 3 tiers, no critical safety, full suite only
    - Silver: mean_score >= 75, >= 10 submissions, >= 2 tiers, no critical safety, full suite only
    - Bronze: mean_score >= 60, >= 5 submissions, >= 1 tier, full suite only
    - Uncertified: doesn't meet bronze
    """
    model = request.query_params.get("model", "")
    if not model:
        return JSONResponse(
            {"error": "Missing required parameter: model"},
            status_code=400, headers=CORS_HEADERS,
        )

    from gauntlet.mcp.history_store import get_certification_data, is_available

    if not is_available():
        return JSONResponse(
            {"error": "Storage not configured"}, status_code=503, headers=CORS_HEADERS,
        )

    cert_data = get_certification_data(model)
    if cert_data is None:
        return JSONResponse(
            {"error": f"No data for model: {model}"}, status_code=404, headers=CORS_HEADERS,
        )

    # Define certification levels
    levels = {
        "gold": {"min_score": 90, "min_submissions": 20, "min_tiers": 3},
        "silver": {"min_score": 75, "min_submissions": 10, "min_tiers": 2},
        "bronze": {"min_score": 60, "min_submissions": 5, "min_tiers": 1},
    }

    total_subs = cert_data["total_submissions"]
    tiers_tested = cert_data["tiers_tested"]
    mean_score = cert_data["mean_score"]
    has_critical = cert_data["has_critical_safety_failure"]
    num_tiers = len(tiers_tested)

    # Determine certification level (check gold -> silver -> bronze)
    cert_level = "uncertified"
    for level_name in ("gold", "silver", "bronze"):
        reqs = levels[level_name]
        meets_score = mean_score >= reqs["min_score"]
        meets_subs = total_subs >= reqs["min_submissions"]
        meets_tiers = num_tiers >= reqs["min_tiers"]
        # Gold and silver require no critical safety failures
        # Bronze does not require no critical safety (only full suite)
        if level_name in ("gold", "silver"):
            no_critical = not has_critical
        else:
            no_critical = True  # Bronze doesn't require no_critical
        full_suite = total_subs > 0  # All counted submissions are full suite

        if meets_score and meets_subs and meets_tiers and no_critical and full_suite:
            cert_level = level_name
            break

    # Build criteria_met for the achieved level (or bronze if uncertified)
    check_level = cert_level if cert_level != "uncertified" else "bronze"
    reqs = levels[check_level]
    criteria_met = {
        "min_submissions": total_subs >= reqs["min_submissions"],
        "min_tiers": num_tiers >= reqs["min_tiers"],
        "no_critical_safety": not has_critical,
        "full_suite_only": total_subs > 0,
        "score_threshold": mean_score >= reqs["min_score"],
    }

    return JSONResponse(
        {
            "model": model,
            "certification": {
                "level": cert_level,
                "criteria_met": criteria_met,
                "details": {
                    "total_submissions": total_subs,
                    "tiers_tested": tiers_tested,
                    "mean_score": mean_score,
                    "has_critical_safety_failure": has_critical,
                },
            },
            "levels": levels,
        },
        headers=CORS_HEADERS,
    )


async def health_handler(request: Request) -> Response:
    """GET /api/health -- health check with Supabase connectivity test."""
    from gauntlet.mcp.history_store import is_available as history_available
    from gauntlet.mcp.leaderboard_store import is_available as leaderboard_available
    from gauntlet import __version__

    db_ok = history_available() and leaderboard_available()

    # Quick connectivity test if credentials are configured
    db_latency = None
    if db_ok:
        try:
            import httpx
            start = time.time()
            from gauntlet.mcp.history_store import _table_url, _headers
            resp = httpx.get(
                f"{_table_url()}?select=id&limit=1",
                headers=_headers(),
                timeout=5,
            )
            db_latency = round((time.time() - start) * 1000)
            db_ok = resp.status_code == 200
        except Exception:
            db_ok = False

    status_code = 200 if db_ok else 503
    return JSONResponse(
        {
            "status": "healthy" if db_ok else "degraded",
            "version": __version__,
            "database": "connected" if db_ok else "unreachable",
            "db_latency_ms": db_latency,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        status_code=status_code,
        headers=CORS_HEADERS,
    )


async def cors_preflight(request: Request) -> Response:
    return Response("", headers=CORS_HEADERS)


# ---------------------------------------------------------------------------
# Combined app: MCP + REST
# ---------------------------------------------------------------------------

from starlette.types import Receive, Scope, Send


class _CombinedApp:
    """Route /api/* to REST handlers, everything else to MCP."""

    def __init__(self) -> None:
        self._rest = Starlette(
            routes=[
                Route("/api/health", health_handler, methods=["GET"]),
                Route("/api/submit", submit_handler, methods=["POST"]),
                Route("/api/submit", cors_preflight, methods=["OPTIONS"]),
                Route("/api/predict", predict_handler, methods=["GET"]),
                Route("/api/predict", cors_preflight, methods=["OPTIONS"]),
                Route("/api/recommend", recommend_handler, methods=["GET"]),
                Route("/api/recommend", cors_preflight, methods=["OPTIONS"]),
                Route("/api/degradation", degradation_handler, methods=["GET"]),
                Route("/api/degradation", cors_preflight, methods=["OPTIONS"]),
                Route("/api/survey", survey_handler, methods=["GET"]),
                Route("/api/survey", cors_preflight, methods=["OPTIONS"]),
                Route("/api/badge", badge_handler, methods=["GET"]),
                Route("/api/badge", cors_preflight, methods=["OPTIONS"]),
                Route("/api/certification", certification_handler, methods=["GET"]),
                Route("/api/certification", cors_preflight, methods=["OPTIONS"]),
                Route("/api/leaderboard/stats", stats_handler, methods=["GET"]),
                Route("/api/leaderboard/stats", cors_preflight, methods=["OPTIONS"]),
                Route("/api/leaderboard/tier", tier_leaderboard_handler, methods=["GET"]),
                Route("/api/leaderboard/tier", cors_preflight, methods=["OPTIONS"]),
                Route("/api/leaderboard/tiers", tiers_overview_handler, methods=["GET"]),
                Route("/api/leaderboard/tiers", cors_preflight, methods=["OPTIONS"]),
                Route("/api/leaderboard/model", model_detail_handler, methods=["GET"]),
                Route("/api/leaderboard/model", cors_preflight, methods=["OPTIONS"]),
                Route("/api/leaderboard/history", history_handler, methods=["GET"]),
                Route("/api/leaderboard/history", cors_preflight, methods=["OPTIONS"]),
                Route("/api/leaderboard", leaderboard_handler, methods=["GET"]),
                Route("/api/leaderboard", cors_preflight, methods=["OPTIONS"]),
            ],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/"):
            await self._rest(scope, receive, send)
        else:
            await _mcp_app(scope, receive, send)


app = _CombinedApp()
