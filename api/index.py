"""Vercel serverless entry point for Gauntlet MCP server + REST API.

Exposes:
  /mcp                      - MCP streamable-http transport
  /api/leaderboard          - Public leaderboard JSON (Elo ratings)
  /api/leaderboard/history  - Test history + aggregated stats for graphs
"""

from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from gauntlet.mcp.server import mcp

# Allow all hosts for public deployment (default only allows localhost)
mcp.settings.transport_security.enable_dns_rebinding_protection = False
mcp.settings.stateless_http = True

_mcp_app = mcp.streamable_http_app()


# ---------------------------------------------------------------------------
# REST API routes
# ---------------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "public, max-age=30, s-maxage=60",
}


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
        min_tests=min_tests,
    )

    # Build active filters for client display
    active_filters = {
        k: v for k, v in params.items()
        if k in ("gpu_class", "quantization", "parameter_size", "provider", "model_family", "os_platform", "min_tests", "source", "exclude_source")
    }

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
    Basic validation prevents obviously fake submissions.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400, headers=CORS_HEADERS)

    # Validate required fields
    model_name = body.get("model_name")
    overall_score = body.get("overall_score")
    if not model_name or overall_score is None:
        return JSONResponse(
            {"error": "Missing required fields: model_name, overall_score"},
            status_code=400, headers=CORS_HEADERS,
        )

    # Basic anti-spam validation
    # 1. Score range check
    if not isinstance(overall_score, (int, float)) or overall_score < 0 or overall_score > 100:
        return JSONResponse({"error": "Invalid score range"}, status_code=400, headers=CORS_HEADERS)

    # 2. Model name length check (prevents junk data)
    if len(model_name) > 100 or len(model_name) < 2:
        return JSONResponse({"error": "Invalid model name"}, status_code=400, headers=CORS_HEADERS)

    # 3. Must have at least some category scores (real runs always have these)
    cat_scores = body.get("category_scores", {})
    if not isinstance(cat_scores, dict) or len(cat_scores) < 2:
        return JSONResponse({"error": "Insufficient category data"}, status_code=400, headers=CORS_HEADERS)

    # 4. Probe count sanity (real runs have 4+ probes even in quick mode)
    total_probes = body.get("total_probes", 0)
    if not isinstance(total_probes, int) or total_probes < 4:
        return JSONResponse({"error": "Invalid probe count"}, status_code=400, headers=CORS_HEADERS)

    # 5. Must have hardware fingerprint (real CLI always sends this)
    if not body.get("hardware") and not body.get("runtime"):
        return JSONResponse({"error": "Missing system fingerprint"}, status_code=400, headers=CORS_HEADERS)

    from gauntlet.mcp.history_store import record_test_result, is_available
    if not is_available():
        return JSONResponse(
            {"error": "Storage not configured"}, status_code=503, headers=CORS_HEADERS,
        )

    # Reconstruct fingerprint from submitted hardware/runtime/model_config
    fingerprint = None
    hw = body.get("hardware")
    rt = body.get("runtime")
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
    )

    return JSONResponse({"status": "ok"}, headers=CORS_HEADERS)


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
                Route("/api/submit", submit_handler, methods=["POST"]),
                Route("/api/submit", cors_preflight, methods=["OPTIONS"]),
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
