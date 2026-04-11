"""Tests for result attestation (Phase 1.3).

Validates build_attestation() produces correct, complete, and
deterministic attestation dicts for community result provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone

import gauntlet
from gauntlet.core.submit import build_attestation


class TestBuildAttestation:
    """Tests for build_attestation()."""

    def test_returns_all_required_fields(self):
        """Attestation dict must contain all seven required keys."""
        att = build_attestation()
        required_keys = {
            "gauntlet_version",
            "benchmark_fingerprint",
            "module_versions",
            "hardware_tier",
            "submission_timestamp",
            "suite_type",
            "probe_count",
        }
        assert set(att.keys()) == required_keys

    def test_gauntlet_version_matches(self):
        """gauntlet_version must match the package __version__."""
        att = build_attestation()
        assert att["gauntlet_version"] == gauntlet.__version__

    def test_timestamp_is_valid_iso8601(self):
        """submission_timestamp must be a parseable ISO 8601 UTC timestamp."""
        att = build_attestation()
        ts = att["submission_timestamp"]
        # Must be a non-empty string
        assert isinstance(ts, str) and len(ts) > 0
        # Must parse without error
        parsed = datetime.fromisoformat(ts)
        # Must be in UTC (offset-aware)
        assert parsed.tzinfo is not None

    def test_default_values(self):
        """Default call with no args produces empty/zero defaults."""
        att = build_attestation()
        assert att["hardware_tier"] == ""
        assert att["benchmark_fingerprint"] == ""
        assert att["module_versions"] == {}
        assert att["suite_type"] == "full"
        assert att["probe_count"] == 0

    def test_full_params_populated(self):
        """All parameters should be reflected in the output."""
        versions = {"SYCOPHANCY_TRAP": "SYCOPHANCY_TRAP:v2:abc123"}
        att = build_attestation(
            hardware_tier="CONSUMER_HIGH",
            benchmark_fingerprint="sha256:deadbeef",
            module_versions=versions,
            suite_type="quick",
            probe_count=42,
        )
        assert att["hardware_tier"] == "CONSUMER_HIGH"
        assert att["benchmark_fingerprint"] == "sha256:deadbeef"
        assert att["module_versions"] == versions
        assert att["suite_type"] == "quick"
        assert att["probe_count"] == 42

    def test_deterministic_except_timestamp(self):
        """Two calls with the same params must produce identical results
        except for submission_timestamp."""
        params = dict(
            hardware_tier="EDGE",
            benchmark_fingerprint="fp123",
            module_versions={"A": "v1"},
            suite_type="full",
            probe_count=10,
        )
        att1 = build_attestation(**params)
        att2 = build_attestation(**params)

        # Remove timestamps for comparison
        ts1 = att1.pop("submission_timestamp")
        ts2 = att2.pop("submission_timestamp")

        # Everything except timestamp is identical
        assert att1 == att2
        # Timestamps are both valid but may differ
        assert isinstance(ts1, str) and isinstance(ts2, str)

    def test_module_versions_none_becomes_empty_dict(self):
        """Passing module_versions=None should produce an empty dict."""
        att = build_attestation(module_versions=None)
        assert att["module_versions"] == {}

    def test_hardware_tier_accepts_all_valid_tiers(self):
        """All valid hardware tier values should be accepted."""
        valid_tiers = ["CLOUD", "CONSUMER_HIGH", "CONSUMER_MID", "CONSUMER_LOW", "EDGE", ""]
        for tier in valid_tiers:
            att = build_attestation(hardware_tier=tier)
            assert att["hardware_tier"] == tier
