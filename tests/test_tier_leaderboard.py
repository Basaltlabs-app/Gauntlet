"""Tests for hardware-stratified leaderboard API (Phase 2.1)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock Supabase row fixtures
# ---------------------------------------------------------------------------

def _make_row(model: str, score: float, tier: str, grade: str = "B") -> dict:
    return {
        "model_name": model,
        "overall_score": score,
        "grade": grade,
        "hardware_tier": tier,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


TIER_ROWS_CONSUMER_MID = [
    _make_row("qwen3:7b", 78.5, "CONSUMER_MID", "B"),
    _make_row("qwen3:7b", 80.2, "CONSUMER_MID", "B+"),
    _make_row("qwen3:7b", 76.9, "CONSUMER_MID", "B"),
    _make_row("qwen3:7b", 79.1, "CONSUMER_MID", "B"),
    _make_row("qwen3:7b", 81.0, "CONSUMER_MID", "B+"),
    _make_row("llama3:8b", 72.3, "CONSUMER_MID", "C+"),
    _make_row("llama3:8b", 71.0, "CONSUMER_MID", "C+"),
    _make_row("llama3:8b", 74.5, "CONSUMER_MID", "B-"),
    _make_row("gemma2:9b", 85.0, "CONSUMER_MID", "A-"),
]

DISTRIBUTION_ROWS = [
    _make_row("gpt-4o", 92.1, "CLOUD", "A"),
    _make_row("gpt-4o", 93.5, "CLOUD", "A"),
    _make_row("claude-3.5", 91.0, "CLOUD", "A"),
    _make_row("qwen3:7b", 78.5, "CONSUMER_MID", "B"),
    _make_row("qwen3:7b", 80.2, "CONSUMER_MID", "B+"),
    _make_row("llama3:8b", 72.3, "CONSUMER_MID", "C+"),
    _make_row("phi3:mini", 65.0, "EDGE", "C"),
]


def _mock_httpx_get(rows: list[dict]):
    """Create a mock httpx.get that returns the given rows."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = rows
    mock_resp.raise_for_status = MagicMock()
    return MagicMock(return_value=mock_resp)


# ---------------------------------------------------------------------------
# Tests: get_tier_leaderboard
# ---------------------------------------------------------------------------

class TestGetTierLeaderboard:
    """Test history_store.get_tier_leaderboard()."""

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_returns_ranked_models(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = TIER_ROWS_CONSUMER_MID
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_leaderboard
        result = get_tier_leaderboard("CONSUMER_MID")

        assert len(result) == 3
        # gemma2:9b has highest score (85.0), should be first
        assert result[0]["model_name"] == "gemma2:9b"
        # qwen3:7b has 5 tests, should be reliable
        assert result[1]["model_name"] == "qwen3:7b"
        assert result[1]["sample_size"] == 5
        assert result[1]["is_reliable"] is True

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_statistics_fields_present(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = TIER_ROWS_CONSUMER_MID
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_leaderboard
        result = get_tier_leaderboard("CONSUMER_MID")

        for entry in result:
            assert "model_name" in entry
            assert "mean" in entry
            assert "ci_lower" in entry
            assert "ci_upper" in entry
            assert "sample_size" in entry
            assert "grade" in entry
            assert "is_reliable" in entry
            # CI should bracket the mean
            assert entry["ci_lower"] <= entry["mean"] <= entry["ci_upper"]

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_empty_tier(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_leaderboard
        result = get_tier_leaderboard("EDGE")
        assert result == []

    @patch("gauntlet.mcp.history_store.is_available", return_value=False)
    def test_unavailable_returns_empty(self, _mock_avail):
        from gauntlet.mcp.history_store import get_tier_leaderboard
        result = get_tier_leaderboard("CLOUD")
        assert result == []

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_limit_respected(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = TIER_ROWS_CONSUMER_MID
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_leaderboard
        result = get_tier_leaderboard("CONSUMER_MID", limit=2)
        assert len(result) <= 2

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_single_test_model(self, mock_get, _mock_avail):
        """A model with only one test should still appear but is_reliable=False."""
        single_row = [_make_row("tiny-model", 60.0, "EDGE", "C")]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = single_row
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_leaderboard
        result = get_tier_leaderboard("EDGE")
        assert len(result) == 1
        assert result[0]["is_reliable"] is False
        assert result[0]["sample_size"] == 1


# ---------------------------------------------------------------------------
# Tests: get_tier_distribution
# ---------------------------------------------------------------------------

class TestGetTierDistribution:
    """Test history_store.get_tier_distribution()."""

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_returns_all_five_tiers(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = DISTRIBUTION_ROWS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_distribution
        result = get_tier_distribution()

        assert "tiers" in result
        assert len(result["tiers"]) == 5
        tier_names = [t["tier"] for t in result["tiers"]]
        assert "CLOUD" in tier_names
        assert "CONSUMER_HIGH" in tier_names
        assert "CONSUMER_MID" in tier_names
        assert "CONSUMER_LOW" in tier_names
        assert "EDGE" in tier_names

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_cloud_tier_counts(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = DISTRIBUTION_ROWS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_distribution
        result = get_tier_distribution()

        cloud = next(t for t in result["tiers"] if t["tier"] == "CLOUD")
        assert cloud["total_tests"] == 3
        assert cloud["unique_models"] == 2  # gpt-4o, claude-3.5
        assert cloud["label"] == "Cloud"

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_total_submissions(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = DISTRIBUTION_ROWS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_distribution
        result = get_tier_distribution()

        assert result["total_submissions"] == 7
        assert "last_updated" in result

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_empty_tiers_have_zero_counts(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = DISTRIBUTION_ROWS
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_distribution
        result = get_tier_distribution()

        consumer_high = next(t for t in result["tiers"] if t["tier"] == "CONSUMER_HIGH")
        assert consumer_high["total_tests"] == 0
        assert consumer_high["unique_models"] == 0

    @patch("gauntlet.mcp.history_store.is_available", return_value=False)
    def test_unavailable_returns_structure(self, _mock_avail):
        from gauntlet.mcp.history_store import get_tier_distribution
        result = get_tier_distribution()
        assert "tiers" in result
        assert result["total_submissions"] == 0

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.httpx.get")
    def test_no_data_returns_empty_tiers(self, mock_get, _mock_avail):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from gauntlet.mcp.history_store import get_tier_distribution
        result = get_tier_distribution()
        assert result["total_submissions"] == 0


# ---------------------------------------------------------------------------
# Tests: API endpoint validation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tests: API endpoint validation
#
# api/index.py imports the MCP server which requires the `mcp` SDK.
# That SDK is not always installed in the test environment. We mock
# the module import chain so we can test the HTTP handlers in isolation.
# ---------------------------------------------------------------------------

def _ensure_mcp_mock():
    """Mock the MCP SDK module if it's not installed."""
    import sys
    from unittest.mock import MagicMock
    if "mcp" not in sys.modules:
        mock_mcp = MagicMock()
        sys.modules["mcp"] = mock_mcp
        sys.modules["mcp.server"] = mock_mcp.server
        sys.modules["mcp.server.fastmcp"] = mock_mcp.server.fastmcp


# Pre-mock MCP before any api.index import attempt
_ensure_mcp_mock()

# Check if we can import the API at all
_can_import_api = True
try:
    from starlette.testclient import TestClient as _TC
    from api.index import app as _app
    _TC(_app)  # Quick smoke test
except Exception:
    _can_import_api = False

_skip_api = pytest.mark.skipif(not _can_import_api, reason="Cannot import api.index (missing dependencies)")


@_skip_api
class TestTierAPIValidation:
    """Test API endpoint parameter validation via Starlette test client."""

    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient
        from api.index import app
        with patch("gauntlet.mcp.history_store.is_available", return_value=True), \
             patch("gauntlet.mcp.history_store.get_tier_leaderboard", return_value=[]), \
             patch("gauntlet.mcp.history_store.get_tier_distribution", return_value={"tiers": [], "total_submissions": 0, "last_updated": None}), \
             patch("gauntlet.mcp.leaderboard_store.is_available", return_value=False):
            yield TestClient(app)

    def test_tier_endpoint_missing_param(self, client):
        resp = client.get("/api/leaderboard/tier")
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data
        assert "Missing" in data["error"]

    def test_tier_endpoint_invalid_tier(self, client):
        resp = client.get("/api/leaderboard/tier?tier=INVALID")
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data
        assert "Invalid tier" in data["error"]

    def test_tier_endpoint_valid_tier(self, client):
        resp = client.get("/api/leaderboard/tier?tier=CLOUD")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "CLOUD"
        assert "models" in data

    def test_tier_endpoint_all_valid_tiers(self, client):
        for tier in ["CLOUD", "CONSUMER_HIGH", "CONSUMER_MID", "CONSUMER_LOW", "EDGE"]:
            resp = client.get(f"/api/leaderboard/tier?tier={tier}")
            assert resp.status_code == 200, f"Failed for tier {tier}"

    def test_tiers_overview_endpoint(self, client):
        resp = client.get("/api/leaderboard/tiers")
        assert resp.status_code == 200
        data = resp.json()
        assert "tiers" in data
        assert "total_submissions" in data

    def test_tier_endpoint_cors_headers(self, client):
        resp = client.get("/api/leaderboard/tier?tier=CLOUD")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_tiers_overview_cors_headers(self, client):
        resp = client.get("/api/leaderboard/tiers")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_tier_endpoint_options_preflight(self, client):
        resp = client.options("/api/leaderboard/tier")
        assert resp.status_code == 200

    def test_tiers_overview_options_preflight(self, client):
        resp = client.options("/api/leaderboard/tiers")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: API with storage unavailable
# ---------------------------------------------------------------------------

@_skip_api
class TestTierAPIStorageUnavailable:
    """Test endpoints when Supabase is not configured."""

    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient
        from api.index import app
        with patch("gauntlet.mcp.history_store.is_available", return_value=False), \
             patch("gauntlet.mcp.leaderboard_store.is_available", return_value=False):
            yield TestClient(app)

    def test_tier_returns_503_when_unavailable(self, client):
        resp = client.get("/api/leaderboard/tier?tier=CLOUD")
        assert resp.status_code == 503

    def test_tiers_returns_empty_when_unavailable(self, client):
        resp = client.get("/api/leaderboard/tiers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_submissions"] == 0
