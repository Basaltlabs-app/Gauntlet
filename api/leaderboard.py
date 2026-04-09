"""REST API endpoint for the public Gauntlet leaderboard.

GET /api/leaderboard -> JSON array of model ratings sorted by Elo.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "public, max-age=30, s-maxage=60",
}


async def leaderboard(request: Request) -> Response:
    """Return the leaderboard as JSON."""
    from gauntlet.mcp.leaderboard_store import get_leaderboard, is_available

    if not is_available():
        return JSONResponse(
            {"models": [], "note": "No models ranked yet. Run gauntlet compare to start."},
            headers=CORS_HEADERS,
        )

    models = get_leaderboard()

    return JSONResponse(
        {
            "models": models,
            "total": len(models),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        headers=CORS_HEADERS,
    )


async def options(request: Request) -> Response:
    """Handle CORS preflight."""
    return Response("", headers=CORS_HEADERS)


app = Starlette(
    routes=[
        Route("/", leaderboard, methods=["GET"]),
        Route("/", options, methods=["OPTIONS"]),
    ],
)
