"""Tiny helper for rendering the save-status block appended to MCP tool
responses. Lives in its own module (no FastMCP imports) so it can be
imported from tests without pulling in the whole MCP server.

Status dict shape (returned by _save_mcp_results):
    {
        "local":     "saved" | "failed: <reason>",
        "community": "saved" | "skipped: <reason>" | "failed: <reason>",
    }
"""

from __future__ import annotations


_MARKER = {
    "saved":    "[ok]",
    "failed":   "[fail]",
    "skipped":  "[skip]",
    "rejected": "[reject]",
}

# Order matters — we want local first since it's the simpler case.
_DESTINATIONS: tuple[tuple[str, str], ...] = (
    ("Local history",        "local"),
    ("Community dashboard",  "community"),
)


def format_save_status(status: dict) -> str:
    """Render status dict as a multi-line block for inclusion in a tool response.

    Output starts with a blank line so it cleanly separates from whatever
    text the runner produced above it.
    """
    lines = ["", "--- Save status ---"]
    for label, key in _DESTINATIONS:
        val = status.get(key, "unknown")
        prefix = val.split(":", 1)[0].strip()
        lines.append(f"  {_MARKER.get(prefix, '[?]')} {label}: {val}")
    return "\n".join(lines)
