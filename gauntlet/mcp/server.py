"""Gauntlet MCP Server — run behavioral benchmarks on the connected AI.

The AI connected to this MCP server IS the test subject. It calls
`gauntlet_run()` to start, then `gauntlet_respond()` repeatedly with
its answers until the benchmark is complete.

Two-tool design prevents the "null response" bug where AI clients pass
response=null instead of their actual answer (Optional[Any] schema
makes null look valid).

Supports multi-session: each concurrent client gets isolated state
via a session_id token returned on first call.

Usage:
    gauntlet mcp                                # stdio (local)
    gauntlet mcp -t sse -p 8484                 # http://localhost:8484/sse
    gauntlet mcp -t streamable-http -p 8484     # http://localhost:8484/mcp
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Optional

from mcp.server.fastmcp import FastMCP

from gauntlet.mcp.runner import GauntletRunner

logger = logging.getLogger("gauntlet.mcp")

# ---------------------------------------------------------------------------
# Session storage — in-memory locally, Supabase on Vercel
# ---------------------------------------------------------------------------

_USE_SUPABASE = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"))

# In-memory fallback for local/Docker use
_runners: dict[str, GauntletRunner] = {}


def _get_runner(session_id: str) -> Optional[GauntletRunner]:
    """Load a runner by session ID."""
    if _USE_SUPABASE:
        from gauntlet.mcp.session_store import load_session
        return load_session(session_id)
    return _runners.get(session_id)


def _save_runner(session_id: str, runner: GauntletRunner) -> None:
    """Persist a runner's state."""
    if _USE_SUPABASE:
        from gauntlet.mcp.session_store import save_session
        save_session(session_id, runner)
    else:
        _runners[session_id] = runner


def _delete_runner(session_id: str) -> None:
    """Remove a completed session."""
    if _USE_SUPABASE:
        from gauntlet.mcp.session_store import delete_session
        delete_session(session_id)
    else:
        _runners.pop(session_id, None)


def _cleanup_stale_sessions() -> None:
    """Purge orphaned sessions (started but never finished).

    Uses probabilistic debouncing: only ~1 in 20 calls actually runs the
    DELETE query. This prevents a thundering herd when many users start
    sessions simultaneously. The pg_cron job handles the rest.
    """
    import random
    if random.random() > 0.05:  # 95% chance to skip — pg_cron handles it
        return

    if _USE_SUPABASE:
        try:
            from gauntlet.mcp.session_store import cleanup_old_sessions
            cleanup_old_sessions(max_age_hours=1)
        except Exception as e:
            logger.debug(f"Session cleanup failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Model name normalization for MCP results
# ---------------------------------------------------------------------------

# Common aliases -> canonical name
_MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus",
    "opus 4": "claude-opus-4",
    "opus 4.6": "claude-opus-4-6",
    "claude opus": "claude-opus",
    "claude opus 4": "claude-opus-4",
    "claude opus 4.6": "claude-opus-4-6",
    "claude-opus-4-6 (1m context)": "claude-opus-4-6",
    "claude-opus-4-6 1m": "claude-opus-4-6",
    "sonnet": "claude-sonnet",
    "sonnet 4": "claude-sonnet-4",
    "claude sonnet": "claude-sonnet",
    "claude-sonnet-4-20250514": "claude-sonnet-4",
    "haiku": "claude-haiku",
    "claude haiku": "claude-haiku",
    "gpt4": "gpt-4",
    "gpt4o": "gpt-4o",
    "gpt 4o": "gpt-4o",
    "gpt-4-turbo": "gpt-4-turbo",
    "gemini": "gemini-pro",
    "gemini pro": "gemini-pro",
    "gemini flash": "gemini-flash",
}


def _normalize_model_name(name: str) -> str:
    """Normalize a model name to a canonical form.

    Returns empty string if the name is invalid (unknown, empty, too short).
    """
    if not name or not name.strip():
        return ""

    cleaned = name.strip().lower()

    # Reject generic/unknown names
    if cleaned in ("unknown", "test", "model", "ai", "assistant", "bot", "llm"):
        return ""

    # Check alias table
    if cleaned in _MODEL_ALIASES:
        return _MODEL_ALIASES[cleaned]

    # Remove common suffixes that add noise
    for suffix in (" (1m context)", " 1m context", " (1m)", " context"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)].strip()

    # Replace spaces and underscores with hyphens for consistency
    cleaned = cleaned.replace(" ", "-").replace("_", "-")

    # Remove consecutive hyphens
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")

    # Strip leading/trailing hyphens
    cleaned = cleaned.strip("-")

    # Must be at least 3 chars to be a valid model name
    if len(cleaned) < 3:
        return ""

    return cleaned


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Gauntlet",
    instructions=(
        "Behavioral benchmark — YOU are the test subject.\n"
        "1. Call gauntlet_run(client_name='your-model-name') to start.\n"
        "2. Read the PROMPT in the response.\n"
        "3. Call gauntlet_respond(response='your actual answer text', session_id='...') to answer.\n"
        "4. Repeat step 2-3 until the benchmark is complete.\n"
        "IMPORTANT: gauntlet_respond() response must be your real answer, never null or empty."
    ),
)


@mcp.tool()
def gauntlet_run(
    client_name: str = "unknown",
    quick: bool = False,
) -> str:
    """Start a new Gauntlet behavioral benchmark. YOU are the test subject.

    This returns a PROMPT. You must ANSWER it by calling gauntlet_respond()
    with your answer text and the session_id shown below.

    Flow: gauntlet_run() -> read prompt -> gauntlet_respond(answer, session_id) -> repeat

    Args:
        client_name: REQUIRED. Your model name (e.g. 'claude-sonnet-4-6', 'gpt-4o').
        quick: Quick suite (17 tests) vs full (56).
    """
    normalized = _normalize_model_name(client_name)
    if not normalized:
        return (
            "ERROR: client_name is required. Pass your model name "
            "(e.g. client_name='claude-sonnet-4-6' or 'gpt-4o'). "
            "Results without a model name are not saved."
        )

    # Opportunistic cleanup: purge orphaned sessions older than 1 hour
    _cleanup_stale_sessions()

    sid = str(uuid.uuid4())[:8]
    runner = GauntletRunner(quick=quick, client_name=normalized)
    result = runner.advance()
    _save_runner(sid, runner)

    header = f"SESSION: {sid}\n{'=' * 50}\n\n"
    return header + result["message"] + (
        f"\n\n---\nIMPORTANT: To answer, call gauntlet_respond(response=\"<your answer>\", session_id=\"{sid}\")"
    )


@mcp.tool()
def gauntlet_respond(
    response: str,
    session_id: str,
) -> str:
    """Submit your answer to the current Gauntlet prompt.

    YOU are being tested. Put YOUR ACTUAL ANSWER to the prompt in 'response'.
    Do NOT pass null or empty string — write the real answer.

    After each call you will receive either the next prompt (call this tool again)
    or your final score.

    Args:
        response: Your answer to the prompt. MUST be a non-empty string containing your actual response.
        session_id: The session ID from gauntlet_run (e.g. 'a1b2c3d4').
    """
    # Coerce response to string — MCP transport may deserialize JSON strings
    # into dicts/lists before they reach us
    if not isinstance(response, str):
        response = json.dumps(response) if isinstance(response, (dict, list)) else str(response)

    if not response or not response.strip():
        return "ERROR: response must be a non-empty string containing your answer to the prompt."

    if not session_id or not session_id.strip():
        return "ERROR: session_id is required. Pass the session_id from your gauntlet_run() call."

    runner = _get_runner(session_id)
    if not runner:
        return f"ERROR: Unknown session '{session_id}'. Start a new run by calling gauntlet_run()."

    if runner.finished:
        return "This benchmark session is complete. Start a new run by calling gauntlet_run()."

    result = runner.advance(response)

    if result["status"] == "complete":
        _save_mcp_results(result["result"], runner.quick)
        _delete_runner(session_id)
        return result["message"]

    if result["status"] == "error":
        return f"ERROR: {result['message']}"

    # Save state after each advance (critical for serverless)
    _save_runner(session_id, runner)
    return result["message"] + (
        f"\n\n---\nCall gauntlet_respond(response=\"<your answer>\", session_id=\"{session_id}\")"
    )


@mcp.tool()
def gauntlet_results() -> str:
    """View results from the most recent Gauntlet run.

    Returns the latest benchmark results from any source (MCP, CLI, or dashboard).
    """
    from gauntlet.core.benchmark_history import get_latest_benchmark

    data = get_latest_benchmark()
    if not data:
        return "No benchmark results found. Run gauntlet_run to test yourself."

    results = data.get("results", [])
    if not results:
        return "No results in the latest benchmark run."

    lines = ["LATEST GAUNTLET RESULTS", "=" * 50, ""]
    for r in results:
        lines.append(f"Model: {r['model']}")
        lines.append(f"Score: {r['overall_score']}%  ({r['total_passed']}/{r['total_tests']} passed)")
        lines.append("")
        for test in r.get("results", []):
            icon = "PASS" if test["passed"] else "FAIL"
            lines.append(f"  {icon}  {test['name']:<35s} {test['score_pct']:>5.1f}%  [{test['category']}]")
        lines.append("")

        if r.get("category_scores"):
            lines.append("  CATEGORIES:")
            for cat, score in r["category_scores"].items():
                bar_len = int(score / 100 * 20)
                bar = "█" * bar_len + "░" * (20 - bar_len)
                lines.append(f"    {cat:<25s} {bar} {score:.0f}%")
            lines.append("")

    lines.append(f"Run: {data.get('timestamp', 'unknown')}")
    lines.append("=" * 50)
    return "\n".join(lines)


@mcp.tool()
def gauntlet_leaderboard() -> str:
    """View the persistent Gauntlet leaderboard.

    Shows trust rankings built from all comparisons and benchmarks across sessions.
    """
    # Try Supabase first (public leaderboard), fall back to local file
    models = []
    try:
        from gauntlet.mcp.leaderboard_store import get_leaderboard, is_available
        if is_available():
            models = get_leaderboard()
    except Exception:
        pass

    if not models:
        from gauntlet.core.leaderboard import Leaderboard
        lb = Leaderboard()
        data = lb.to_dict()
        models = data.get("models", [])

    if not models:
        return "No leaderboard data yet. Run benchmarks or comparisons to build rankings."

    lines = ["GAUNTLET RANKINGS", "=" * 60, ""]
    lines.append(f"  {'#':<4s} {'Model':<30s} {'Rating':>6s}  {'W/L/D':>10s}  {'Win%':>5s}")
    lines.append("  " + "-" * 56)

    for i, m in enumerate(models):
        lines.append(
            f"  {i+1:<4d} {m['name']:<30s} {m.get('rating', m.get('elo', 1500)):>6.0f}  "
            f"{m['wins']}/{m['losses']}/{m['draws']:>10s}  "
            f"{m['win_rate']:>5.1f}%"
        )

    lines.append("")
    lines.append(f"  {len(models)} models ranked")
    lines.append("=" * 60)
    return "\n".join(lines)


def _save_mcp_results(result_dict: dict, quick: bool):
    """Persist MCP benchmark results to the same store as CLI/dashboard."""
    try:
        from gauntlet.core.benchmark_history import save_benchmark_run
        save_benchmark_run([result_dict], quick=quick)
        logger.info("Benchmark results saved")
    except Exception as e:
        logger.warning(f"Failed to save benchmark results: {e}")

    # Also push to public test history
    try:
        from gauntlet.mcp.history_store import record_test_result, is_available
        if is_available():
            # MCP runs on Vercel serverless, limited fingerprint (no local hardware)
            from gauntlet.core.system_info import SystemFingerprint
            mcp_fingerprint = SystemFingerprint(
                provider="mcp",
                model_family=result_dict.get("model", "unknown").split(":")[0],
                quantization="cloud",
                model_format="api",
                os_platform="serverless",
            )

            record_test_result(
                model_name=result_dict.get("model", "unknown"),
                overall_score=result_dict.get("overall_score", 0),
                trust_score=result_dict.get("trust_score", 0),
                grade=result_dict.get("grade", "?"),
                category_scores=result_dict.get("category_scores", {}),
                total_probes=result_dict.get("total_tests", 0),
                passed_probes=result_dict.get("total_passed", 0),
                source="mcp",
                quick=quick,
                fingerprint=mcp_fingerprint,
            )
    except Exception as e:
        logger.warning(f"Failed to push to test history: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_server(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8484):
    """Start the MCP server."""
    mcp.settings.host = host
    mcp.settings.port = port

    if transport in ("sse", "streamable-http"):
        print(f"Gauntlet MCP server starting on http://{host}:{port}")
        if transport == "sse":
            print(f"  SSE endpoint:  http://{host}:{port}/sse")
        else:
            print(f"  HTTP endpoint: http://{host}:{port}/mcp")

    mcp.run(transport=transport)
