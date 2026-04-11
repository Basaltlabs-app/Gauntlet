"""Vercel serverless entry point for Gauntlet MCP server + REST API.

Exposes:
  /mcp                      - MCP streamable-http transport
  /api/leaderboard          - Public leaderboard JSON (Elo ratings)
  /api/leaderboard/history  - Test history + aggregated stats for graphs
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

# Known valid category names from registered modules
VALID_CATEGORIES = {
    "AMBIGUITY_HONESTY", "SYCOPHANCY_TRAP", "INSTRUCTION_ADHERENCE",
    "CONSISTENCY_DRIFT", "SAFETY_BOUNDARY", "HALLUCINATION_PROBE",
    "CONTEXT_FIDELITY", "REFUSAL_CALIBRATION", "CONTAMINATION_CHECK",
    "TEMPORAL_COHERENCE", "INSTRUCTION_DECAY", "SYCOPHANCY_GRADIENT",
    "CONFIDENCE_CALIBRATION",
    # v1.3.7: cognitive bias + security modules
    "ANCHORING_BIAS", "PROMPT_INJECTION", "LOGICAL_CONSISTENCY", "FRAMING_EFFECT",
    # Benchmark/compare categories (from scorer)
    "speed", "quality", "responsiveness", "overall",
}

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

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Gauntlet-Signature",
    "Cache-Control": "public, max-age=30, s-maxage=60",
}


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
    # ── 1. Rate limiting (per IP) ────────────────────────────────────────
    client_ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                 or request.client.host if request.client else "unknown")
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
        # Allow 25-point tolerance (profiles weight categories differently)
        if abs(overall_score - cat_avg) > 25:
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

    record_test_result(
        model_name=model_name,
        overall_score=body.get("overall_score", 0),
        trust_score=body.get("trust_score", 0),
        grade=body.get("grade", "?"),
        category_scores=body.get("category_scores", {}),
        total_probes=body.get("total_probes", 0),
        passed_probes=body.get("passed_probes", 0),
        source=body.get("source", "cli"),
        quick=body.get("quick", False),
        fingerprint=fingerprint,
        probe_details=body.get("probe_details"),
        attestation=body.get("attestation"),
        hardware_tier=body.get("hardware_tier", ""),
    )

    return JSONResponse({"status": "ok"}, headers=CORS_HEADERS)


async def stats_handler(request: Request) -> Response:
    """GET /api/leaderboard/stats -- community aggregate statistics."""
    from gauntlet.mcp.history_store import get_community_stats, is_available

    if not is_available():
        return JSONResponse({"total_tests": 0}, headers=CORS_HEADERS)

    stats = get_community_stats()
    return JSONResponse(stats, headers=CORS_HEADERS)


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
                Route("/api/leaderboard/stats", stats_handler, methods=["GET"]),
                Route("/api/leaderboard/stats", cors_preflight, methods=["OPTIONS"]),
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
