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
        min_tests=min_tests,
    )

    # Build active filters for client display
    active_filters = {
        k: v for k, v in params.items()
        if k in ("gpu_class", "quantization", "parameter_size", "provider", "model_family", "os_platform", "min_tests")
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
