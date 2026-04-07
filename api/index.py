"""Vercel serverless entry point for Gauntlet MCP server.

Exposes the FastMCP Starlette app at /mcp for streamable-http transport.
Session state is persisted in Supabase (set SUPABASE_URL and SUPABASE_SERVICE_KEY
in Vercel environment variables).
"""

from gauntlet.mcp.server import mcp

# Allow all hosts for public deployment (default only allows localhost)
mcp.settings.transport_security.enable_dns_rebinding_protection = False
mcp.settings.stateless_http = True

app = mcp.streamable_http_app()
