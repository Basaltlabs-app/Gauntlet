"""Tests for module versioning: content_hash, versioned_id, and GauntletScore version fields."""
from __future__ import annotations

import re

import pytest
from unittest.mock import patch

from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleResult,
    ModuleScore,
    Probe,
    Severity,
)
from gauntlet.core.scorer import (
    GauntletScore,
    compute_gauntlet_score,
    _compute_benchmark_fingerprint,
)


# ---------------------------------------------------------------------------
# Helpers: concrete module subclass for testing
# ---------------------------------------------------------------------------

class _StubModule(GauntletModule):
    """Minimal concrete GauntletModule for testing content_hash/versioned_id."""

    name = "STUB_MODULE"
    description = "A stub module for testing"
    version = "0.1.0"

    def __init__(self, probes: list[Probe] | None = None):
        self._probes = probes or []

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        return list(self._probes)

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        return True, 1.0, "ok"


def _make_probe(
    probe_id: str = "p1",
    name: str = "Test probe",
    severity: Severity = Severity.MEDIUM,
    expected: str = "expected",
    messages: list[tuple[str, str]] | None = None,
) -> Probe:
    return Probe(
        id=probe_id,
        name=name,
        description="test",
        severity=severity,
        expected=expected,
        messages=messages or [("user", "hello")],
    )


def _ms(
    module_name: str = "TEST_MODULE",
    score: float = 1.0,
    passed: int = 5,
    failed: int = 0,
    total: int = 5,
    critical_failures: int = 0,
    high_failures: int = 0,
) -> ModuleScore:
    """Shorthand for building a ModuleScore."""
    return ModuleScore(
        module_name=module_name,
        score=score,
        grade=ModuleScore.grade_from_score(score, critical_failures),
        passed=passed,
        failed=failed,
        total=total,
        critical_failures=critical_failures,
        high_failures=high_failures,
        summary=f"{module_name}: {score:.0%}",
    )


# ---------------------------------------------------------------------------
# Tests: content_hash
# ---------------------------------------------------------------------------

class TestContentHash:
    """content_hash() on GauntletModule base class."""

    def test_returns_8_char_hex(self):
        """content_hash() should return an 8-character hexadecimal string."""
        probes = [_make_probe("p1", "Probe one")]
        mod = _StubModule(probes=probes)
        h = mod.content_hash()
        assert len(h) == 8
        assert re.fullmatch(r"[0-9a-f]{8}", h), f"Not valid hex: {h}"

    def test_same_probes_same_hash(self):
        """Identical probe definitions produce identical hashes."""
        probes = [
            _make_probe("p1", "Probe one", messages=[("user", "Q1")]),
            _make_probe("p2", "Probe two", messages=[("user", "Q2")]),
        ]
        mod_a = _StubModule(probes=list(probes))
        mod_b = _StubModule(probes=list(probes))
        assert mod_a.content_hash() == mod_b.content_hash()

    def test_different_probes_different_hash(self):
        """Changing probe content should change the hash."""
        probes_a = [_make_probe("p1", "Probe one", messages=[("user", "Q1")])]
        probes_b = [_make_probe("p1", "Probe one", messages=[("user", "Different question")])]
        mod_a = _StubModule(probes=probes_a)
        mod_b = _StubModule(probes=probes_b)
        assert mod_a.content_hash() != mod_b.content_hash()

    def test_empty_probes_returns_valid_hash(self):
        """Even with no probes, content_hash should return a valid 8-char hex."""
        mod = _StubModule(probes=[])
        h = mod.content_hash()
        assert len(h) == 8
        assert re.fullmatch(r"[0-9a-f]{8}", h)

    def test_hash_uses_seed_42(self):
        """content_hash calls build_probes with seed=42."""
        probes = [_make_probe("p1")]
        mod = _StubModule(probes=probes)
        with patch.object(mod, "build_probes", wraps=mod.build_probes) as mock_bp:
            mod.content_hash()
            mock_bp.assert_called_once_with(quick=False, seed=42)

    def test_hash_deterministic_across_calls(self):
        """Multiple calls return the same value."""
        probes = [_make_probe("p1"), _make_probe("p2")]
        mod = _StubModule(probes=probes)
        assert mod.content_hash() == mod.content_hash()

    def test_probe_order_matters(self):
        """Probe order affects hash (probes are ordered, not set-like)."""
        p1 = _make_probe("p1", "First")
        p2 = _make_probe("p2", "Second")
        mod_ab = _StubModule(probes=[p1, p2])
        mod_ba = _StubModule(probes=[p2, p1])
        assert mod_ab.content_hash() != mod_ba.content_hash()

    def test_severity_change_affects_hash(self):
        """Changing severity changes the hash."""
        probes_med = [_make_probe("p1", severity=Severity.MEDIUM)]
        probes_crit = [_make_probe("p1", severity=Severity.CRITICAL)]
        mod_med = _StubModule(probes=probes_med)
        mod_crit = _StubModule(probes=probes_crit)
        assert mod_med.content_hash() != mod_crit.content_hash()


# ---------------------------------------------------------------------------
# Tests: versioned_id
# ---------------------------------------------------------------------------

class TestVersionedId:
    """versioned_id property on GauntletModule."""

    def test_format(self):
        """versioned_id should be 'version.hash' format."""
        probes = [_make_probe("p1")]
        mod = _StubModule(probes=probes)
        vid = mod.versioned_id
        # Format: X.Y.Z.abcdef12
        parts = vid.split(".")
        assert len(parts) == 4, f"Expected 4 dot-separated parts, got {parts}"
        # First three are the semantic version
        assert parts[:3] == ["0", "1", "0"]
        # Last is the 8-char hex hash
        assert re.fullmatch(r"[0-9a-f]{8}", parts[3])

    def test_versioned_id_changes_with_probes(self):
        """versioned_id reflects probe content changes via hash."""
        probes_a = [_make_probe("p1", messages=[("user", "Q1")])]
        probes_b = [_make_probe("p1", messages=[("user", "Q2")])]
        mod_a = _StubModule(probes=probes_a)
        mod_b = _StubModule(probes=probes_b)
        assert mod_a.versioned_id != mod_b.versioned_id
        # But both start with the same version prefix
        assert mod_a.versioned_id.startswith("0.1.0.")
        assert mod_b.versioned_id.startswith("0.1.0.")

    def test_versioned_id_changes_with_version(self):
        """Changing the version attribute changes versioned_id."""
        probes = [_make_probe("p1")]
        mod = _StubModule(probes=probes)
        vid_old = mod.versioned_id
        mod.version = "0.2.0"
        vid_new = mod.versioned_id
        assert vid_old != vid_new
        assert vid_new.startswith("0.2.0.")


# ---------------------------------------------------------------------------
# Tests: GauntletScore version fields
# ---------------------------------------------------------------------------

class TestGauntletScoreVersionFields:
    """GauntletScore includes gauntlet_version, module_versions, benchmark_fingerprint."""

    def test_default_values(self):
        """New GauntletScore has empty version fields by default."""
        gs = GauntletScore(model="m", profile="raw", overall_score=0.5, overall_grade="D")
        assert gs.gauntlet_version == ""
        assert gs.module_versions == {}
        assert gs.benchmark_fingerprint == ""

    def test_compute_populates_gauntlet_version(self):
        """compute_gauntlet_score sets gauntlet_version from gauntlet.__version__."""
        import gauntlet
        gs = compute_gauntlet_score("m", [_ms("X", score=0.8)], profile="raw")
        assert gs.gauntlet_version == gauntlet.__version__

    def test_compute_populates_module_versions(self):
        """compute_gauntlet_score stores module_versions when provided."""
        mv = {"SYCOPHANCY_TRAP": "0.1.0.abcd1234", "SAFETY": "0.1.0.ef567890"}
        gs = compute_gauntlet_score(
            "m", [_ms("SYCOPHANCY_TRAP"), _ms("SAFETY")],
            profile="raw", module_versions=mv,
        )
        assert gs.module_versions == mv

    def test_compute_without_module_versions(self):
        """compute_gauntlet_score works without module_versions (backward compat)."""
        gs = compute_gauntlet_score("m", [_ms("X")], profile="raw")
        assert gs.module_versions == {}
        assert gs.benchmark_fingerprint == ""

    def test_to_dict_includes_version_fields(self):
        """to_dict() includes the new version fields."""
        mv = {"MOD_A": "0.1.0.aabbccdd"}
        gs = compute_gauntlet_score("m", [_ms("MOD_A")], profile="raw", module_versions=mv)
        d = gs.to_dict()
        assert "gauntlet_version" in d
        assert "module_versions" in d
        assert "benchmark_fingerprint" in d
        assert d["module_versions"] == mv
        assert d["gauntlet_version"] != ""


# ---------------------------------------------------------------------------
# Tests: benchmark_fingerprint
# ---------------------------------------------------------------------------

class TestBenchmarkFingerprint:
    """benchmark_fingerprint is a deterministic hash of module_versions."""

    def test_deterministic(self):
        """Same module_versions always produce same fingerprint."""
        mv = {"MOD_A": "0.1.0.aabb", "MOD_B": "0.2.0.ccdd"}
        fp1 = _compute_benchmark_fingerprint(mv)
        fp2 = _compute_benchmark_fingerprint(mv)
        assert fp1 == fp2

    def test_different_versions_different_fingerprint(self):
        """Different module_versions produce different fingerprints."""
        mv_a = {"MOD_A": "0.1.0.aabb", "MOD_B": "0.2.0.ccdd"}
        mv_b = {"MOD_A": "0.1.0.aabb", "MOD_B": "0.2.0.eeff"}
        assert _compute_benchmark_fingerprint(mv_a) != _compute_benchmark_fingerprint(mv_b)

    def test_order_independent(self):
        """Dict insertion order should not affect fingerprint (sorted internally)."""
        mv_1 = {"MOD_B": "0.2.0.ccdd", "MOD_A": "0.1.0.aabb"}
        mv_2 = {"MOD_A": "0.1.0.aabb", "MOD_B": "0.2.0.ccdd"}
        assert _compute_benchmark_fingerprint(mv_1) == _compute_benchmark_fingerprint(mv_2)

    def test_empty_returns_empty_string(self):
        """Empty module_versions returns empty fingerprint."""
        assert _compute_benchmark_fingerprint({}) == ""

    def test_fingerprint_is_hex(self):
        """Fingerprint should be a 16-char hex string."""
        mv = {"MOD_A": "0.1.0.aabb"}
        fp = _compute_benchmark_fingerprint(mv)
        assert len(fp) == 16
        assert re.fullmatch(r"[0-9a-f]{16}", fp)

    def test_score_fingerprint_matches_direct(self):
        """GauntletScore.benchmark_fingerprint matches _compute_benchmark_fingerprint."""
        mv = {"MOD_A": "0.1.0.aabb", "MOD_B": "0.2.0.ccdd"}
        gs = compute_gauntlet_score("m", [_ms("MOD_A"), _ms("MOD_B")], profile="raw", module_versions=mv)
        assert gs.benchmark_fingerprint == _compute_benchmark_fingerprint(mv)
