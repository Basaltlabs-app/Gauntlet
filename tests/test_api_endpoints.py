"""Tests for Phase 2.2–2.4 API endpoints: degradation, survey, badge.

The api/index module imports gauntlet.mcp.server which depends on the
`mcp` package (FastMCP).  That package is not installed in the test
environment, so we patch sys.modules to provide a lightweight stub
before importing the application.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from types import ModuleType
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Stub out the heavy `mcp` dependency so api/index can be imported
# ---------------------------------------------------------------------------

def _ensure_mcp_stubs():
    """Insert fake `mcp` modules into sys.modules if not already present."""
    if "mcp" in sys.modules:
        return  # Real package available — nothing to do

    # Create a minimal stub for mcp.server.fastmcp.FastMCP
    mcp_mod = ModuleType("mcp")
    mcp_server = ModuleType("mcp.server")
    mcp_fastmcp = ModuleType("mcp.server.fastmcp")

    class _FakeFastMCP:
        def __init__(self, *a, **kw):
            self.settings = MagicMock()

        def streamable_http_app(self):
            async def _dummy(scope, receive, send):
                pass
            return _dummy

        def tool(self, *a, **kw):
            def decorator(fn):
                return fn
            return decorator

    mcp_fastmcp.FastMCP = _FakeFastMCP
    mcp_mod.server = mcp_server
    mcp_server.fastmcp = mcp_fastmcp

    sys.modules.setdefault("mcp", mcp_mod)
    sys.modules.setdefault("mcp.server", mcp_server)
    sys.modules.setdefault("mcp.server.fastmcp", mcp_fastmcp)


_ensure_mcp_stubs()

from starlette.testclient import TestClient


def _get_app():
    """Import the combined ASGI app (deferred to avoid import-time side effects)."""
    from api.index import app
    return app


# ===========================================================================
# 2.2 Degradation Curves  /api/degradation
# ===========================================================================

class TestDegradationEndpoint:
    """Tests for GET /api/degradation."""

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_scores_by_quantization")
    def test_degradation_with_mock_quantization_data(self, mock_get_scores, mock_avail):
        """Happy path: returns levels and degradation for valid family+size."""
        mock_get_scores.return_value = {
            "fp16": [85.0, 86.0, 84.0],
            "q8_0": [82.0, 83.0, 81.0],
            "q4_k_m": [76.0, 78.0, 77.0],
        }

        client = TestClient(_get_app())
        resp = client.get("/api/degradation?model_family=llama&parameter_size=7b")
        assert resp.status_code == 200

        data = resp.json()
        assert data["model_family"] == "llama"
        assert data["parameter_size"] == "7b"

        # All three quantization levels should have stats
        assert "fp16" in data["levels"]
        assert "q8_0" in data["levels"]
        assert "q4_k_m" in data["levels"]

        # Each level has mean, sample_size, ci_lower, ci_upper
        for level_key in ("fp16", "q8_0", "q4_k_m"):
            level = data["levels"][level_key]
            assert "mean" in level
            assert "sample_size" in level
            assert "ci_lower" in level
            assert "ci_upper" in level
            assert level["sample_size"] == 3

        # fp16 mean should be ~85, q8_0 ~82, q4_k_m ~77
        assert 84 <= data["levels"]["fp16"]["mean"] <= 86
        assert 81 <= data["levels"]["q8_0"]["mean"] <= 83

        # Degradation should show negative drops
        assert "degradation" in data
        assert "fp16_to_q8_0" in data["degradation"]
        assert data["degradation"]["fp16_to_q8_0"] < 0

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_scores_by_quantization")
    def test_degradation_missing_params(self, mock_get_scores, mock_avail):
        """Missing model_family or parameter_size returns 400."""
        client = TestClient(_get_app())

        # Missing parameter_size
        resp = client.get("/api/degradation?model_family=llama")
        assert resp.status_code == 400

        # Missing model_family
        resp = client.get("/api/degradation?parameter_size=7b")
        assert resp.status_code == 400

        # Both missing
        resp = client.get("/api/degradation")
        assert resp.status_code == 400

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_scores_by_quantization")
    def test_degradation_no_data_returns_404(self, mock_get_scores, mock_avail):
        """Returns 404 when no data found for the given family+size."""
        mock_get_scores.return_value = {}

        client = TestClient(_get_app())
        resp = client.get("/api/degradation?model_family=nonexistent&parameter_size=999b")
        assert resp.status_code == 404


# ===========================================================================
# 2.3 Community Hardware Survey  /api/survey
# ===========================================================================

class TestSurveyEndpoint:
    """Tests for GET /api/survey."""

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_survey_stats")
    def test_survey_returns_all_distribution_keys(self, mock_survey, mock_avail):
        """Survey response includes all required distribution keys."""
        mock_survey.return_value = {
            "total_submissions": 1200,
            "tier_distribution": {"CLOUD": 45.2, "CONSUMER_HIGH": 12.1},
            "gpu_distribution": {"apple_silicon": 38.5, "nvidia": 42.1},
            "ram_distribution": {"16gb": 28.3, "32gb": 35.1},
            "os_distribution": {"darwin": 52.1, "linux": 41.3},
            "quantization_distribution": {"q4_k_m": 35.2, "q8_0": 22.1},
        }

        client = TestClient(_get_app())
        resp = client.get("/api/survey")
        assert resp.status_code == 200

        data = resp.json()
        assert "total_submissions" in data
        assert data["total_submissions"] == 1200
        assert "tier_distribution" in data
        assert "gpu_distribution" in data
        assert "ram_distribution" in data
        assert "os_distribution" in data
        assert "quantization_distribution" in data

    @patch("gauntlet.mcp.history_store.is_available", return_value=False)
    def test_survey_unavailable_storage(self, mock_avail):
        """Returns empty stats when storage is unavailable."""
        client = TestClient(_get_app())
        resp = client.get("/api/survey")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_submissions"] == 0

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_survey_stats")
    def test_survey_distribution_percentages_sum(self, mock_survey, mock_avail):
        """Distribution percentages should sum to ~100 when data is present."""
        mock_survey.return_value = {
            "total_submissions": 100,
            "tier_distribution": {"CLOUD": 50.0, "CONSUMER_MID": 30.0, "EDGE": 20.0},
            "gpu_distribution": {"nvidia": 60.0, "apple_silicon": 40.0},
            "ram_distribution": {"16gb": 40.0, "32gb": 60.0},
            "os_distribution": {"darwin": 50.0, "linux": 50.0},
            "quantization_distribution": {"q4_k_m": 100.0},
        }

        client = TestClient(_get_app())
        resp = client.get("/api/survey")
        data = resp.json()

        # Each distribution percentages should sum to ~100
        for dist_key in ("tier_distribution", "gpu_distribution", "os_distribution"):
            dist = data[dist_key]
            total_pct = sum(dist.values())
            assert 99.5 <= total_pct <= 100.5, f"{dist_key} sums to {total_pct}"


# ===========================================================================
# 2.4 Embeddable Badges  /api/badge
# ===========================================================================

class TestBadgeEndpoint:
    """Tests for GET /api/badge."""

    def _parse_svg(self, content: str) -> ET.Element:
        """Parse SVG content as XML, raising if invalid."""
        return ET.fromstring(content)

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_svg_is_valid_xml(self, mock_detail, mock_avail):
        """Badge returns well-formed SVG XML."""
        mock_detail.return_value = {
            "overall": {"grade": "A", "avg_score": 92.5},
        }

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=test-model")
        assert resp.status_code == 200
        assert "image/svg+xml" in resp.headers.get("content-type", "")

        # Parse as XML -- will raise if malformed
        root = self._parse_svg(resp.text)
        assert root.tag == "{http://www.w3.org/2000/svg}svg"

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_color_mapping_grade_a(self, mock_detail, mock_avail):
        """Grade A badge uses green color (#4c1)."""
        mock_detail.return_value = {"overall": {"grade": "A", "avg_score": 95.0}}

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=test-model")
        assert "#4c1" in resp.text

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_color_mapping_grade_b(self, mock_detail, mock_avail):
        """Grade B badge uses yellowgreen color (#a4a61d)."""
        mock_detail.return_value = {"overall": {"grade": "B", "avg_score": 82.0}}

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=test-model")
        assert "#a4a61d" in resp.text

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_color_mapping_grade_c(self, mock_detail, mock_avail):
        """Grade C badge uses yellow color (#dfb317)."""
        mock_detail.return_value = {"overall": {"grade": "C", "avg_score": 72.0}}

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=test-model")
        assert "#dfb317" in resp.text

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_color_mapping_grade_d(self, mock_detail, mock_avail):
        """Grade D badge uses orange color (#fe7d37)."""
        mock_detail.return_value = {"overall": {"grade": "D", "avg_score": 55.0}}

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=test-model")
        assert "#fe7d37" in resp.text

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_color_mapping_grade_f(self, mock_detail, mock_avail):
        """Grade F badge uses red color (#e05d44)."""
        mock_detail.return_value = {"overall": {"grade": "F", "avg_score": 35.0}}

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=test-model")
        assert "#e05d44" in resp.text

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_missing_model_returns_no_data(self, mock_detail, mock_avail):
        """Badge with no model data returns gray 'no data' badge."""
        mock_detail.return_value = None

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=nonexistent-model")
        assert resp.status_code == 200
        assert "image/svg+xml" in resp.headers.get("content-type", "")
        assert "no data" in resp.text
        # Should use gray color
        assert "#9f9f9f" in resp.text

    def test_badge_no_model_param_returns_no_data(self):
        """Badge with empty model param returns gray 'no data' badge."""
        client = TestClient(_get_app())
        resp = client.get("/api/badge")
        assert resp.status_code == 200
        assert "no data" in resp.text

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_cache_control_header(self, mock_detail, mock_avail):
        """Badge response has Cache-Control: max-age=3600."""
        mock_detail.return_value = {"overall": {"grade": "B", "avg_score": 80.0}}

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=test-model")
        cache = resp.headers.get("cache-control", "")
        assert "max-age=3600" in cache

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_model_detail")
    def test_badge_contains_score_in_value(self, mock_detail, mock_avail):
        """Badge displays grade and score."""
        mock_detail.return_value = {"overall": {"grade": "A", "avg_score": 92.5}}

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=test-model")
        assert "A (92.5)" in resp.text

    @patch("gauntlet.mcp.history_store.is_available", return_value=True)
    @patch("gauntlet.mcp.history_store.get_tier_leaderboard")
    def test_badge_with_tier_parameter(self, mock_tier_lb, mock_avail):
        """Badge with tier param uses tier-specific lookup."""
        mock_tier_lb.return_value = [
            {"model_name": "qwen2.5:14b", "mean": 88.0, "grade": "B",
             "ci_lower": 85, "ci_upper": 91, "sample_size": 5, "is_reliable": True},
        ]

        client = TestClient(_get_app())
        resp = client.get("/api/badge?model=qwen2.5:14b&tier=CONSUMER_MID")
        assert resp.status_code == 200
        assert "B (88.0)" in resp.text
        assert "#a4a61d" in resp.text


# ===========================================================================
# Badge SVG generator unit tests
# ===========================================================================

class TestBadgeSVGGenerator:
    """Unit tests for _generate_badge_svg function."""

    def test_generates_valid_svg(self):
        from api.index import _generate_badge_svg
        svg = _generate_badge_svg("test", "value", "#4c1")
        root = ET.fromstring(svg)
        assert root.tag == "{http://www.w3.org/2000/svg}svg"

    def test_label_and_value_in_svg(self):
        from api.index import _generate_badge_svg
        svg = _generate_badge_svg("gauntlet", "A (95.0)", "#4c1")
        assert "gauntlet" in svg
        assert "A (95.0)" in svg

    def test_color_applied(self):
        from api.index import _generate_badge_svg
        svg = _generate_badge_svg("label", "val", "#e05d44")
        assert "#e05d44" in svg

    def test_width_scales_with_text(self):
        from api.index import _generate_badge_svg
        short_svg = _generate_badge_svg("a", "b", "#000")
        long_svg = _generate_badge_svg("long label here", "long value here", "#000")
        # Parse widths
        short_root = ET.fromstring(short_svg)
        long_root = ET.fromstring(long_svg)
        short_w = float(short_root.get("width", "0"))
        long_w = float(long_root.get("width", "0"))
        assert long_w > short_w
