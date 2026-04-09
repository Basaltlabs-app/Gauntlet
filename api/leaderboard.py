"""REST API endpoint for the public Gauntlet leaderboard.

GET /api/leaderboard → JSON array of model ratings sorted by Elo.

Used by basaltlabs.app/gauntlet/leaderboard to display public rankings.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


async def leaderboard(request: Request) -> JSONResponse:
    """Return the leaderboard as JSON."""
    from gauntlet.mcp.leaderboard_store import get_leaderboard, is_available

    if not is_available():
        return JSONResponse(
            {"models": [], "error": "Leaderboard storage not configured"},
            status_code=503,
        )

    models = get_leaderboard()

    return JSONResponse(
        {
            "models": models,
            "total": len(models),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Cache-Control": "public, max-age=30, s-maxage=60",
        },
    )


async def options(request: Request) -> JSONResponse:
    """Handle CORS preflight."""
    return JSONResponse(
        {},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


app = Starlette(
    routes=[
        Route("/api/leaderboard", leaderboard, methods=["GET"]),
        Route("/api/leaderboard", options, methods=["OPTIONS"]),
    ],
)
