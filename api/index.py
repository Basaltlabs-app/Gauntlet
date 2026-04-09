"""Vercel serverless entry point for Gauntlet MCP server + REST API.

Exposes:
  /mcp              - MCP streamable-http transport
  /api/leaderboard  - Public leaderboard JSON API
"""

from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

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


async def cors_preflight(request: Request) -> Response:
    return Response("", headers=CORS_HEADERS)


# ---------------------------------------------------------------------------
# Combined app: MCP + REST
# ---------------------------------------------------------------------------

# The MCP app handles /mcp internally. We wrap it so /api/leaderboard is
# handled first, then everything else falls through to the MCP app.

from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send


class _CombinedApp:
    """Route /api/leaderboard to our handler, everything else to MCP."""

    def __init__(self) -> None:
        self._rest = Starlette(
            routes=[
                Route("/api/leaderboard", leaderboard_handler, methods=["GET"]),
                Route("/api/leaderboard", cors_preflight, methods=["OPTIONS"]),
            ],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith("/api/leaderboard"):
            await self._rest(scope, receive, send)
        else:
            await _mcp_app(scope, receive, send)


app = _CombinedApp()
