"""Tests for format_save_status — the user-facing summary appended to
gauntlet_respond's completion message. This is what tells the user whether
their MCP run actually landed on the dashboard.
"""

from __future__ import annotations

from gauntlet.mcp.save_status import format_save_status


def test_both_saved():
    out = format_save_status({"local": "saved", "community": "saved"})
    assert "[ok] Local history: saved" in out
    assert "[ok] Community dashboard: saved" in out


def test_local_saved_community_skipped_due_to_env():
    skip_msg = (
        "skipped: SUPABASE_URL / SUPABASE_SERVICE_KEY not set in this "
        "process env (check your MCP client's server config or place them "
        "in .env / .env.vercel.local at the repo root)"
    )
    out = format_save_status({"local": "saved", "community": skip_msg})
    assert "[ok] Local history: saved" in out
    assert "[skip] Community dashboard:" in out
    # Full reason carried through so the user sees what to fix
    assert "SUPABASE_URL" in out


def test_community_failed():
    out = format_save_status({"local": "saved", "community": "failed: ConnectTimeout"})
    assert "[ok] Local history: saved" in out
    assert "[fail] Community dashboard: failed: ConnectTimeout" in out


def test_unknown_status_uses_question_mark():
    out = format_save_status({"local": "weird-state", "community": "saved"})
    assert "[?] Local history: weird-state" in out


def test_missing_keys_default_to_unknown():
    out = format_save_status({})
    assert "Local history: unknown" in out
    assert "Community dashboard: unknown" in out


def test_output_starts_with_blank_line_and_header():
    """The block sits at the end of an existing message — the leading
    blank line keeps it from running into prior text."""
    out = format_save_status({"local": "saved", "community": "saved"})
    lines = out.split("\n")
    assert lines[0] == ""
    assert lines[1] == "--- Save status ---"


def test_local_first_then_community():
    """Order is part of the contract — users scan top-down and the local
    write is the simpler of the two."""
    out = format_save_status({"local": "saved", "community": "saved"})
    local_idx = out.index("Local history")
    community_idx = out.index("Community dashboard")
    assert local_idx < community_idx
