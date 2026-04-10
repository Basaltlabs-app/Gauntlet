"""Tests for module base classes: ModuleScore, ProbeResult, ModuleResult, Severity."""
from __future__ import annotations

import pytest
from gauntlet.core.modules.base import (
    ModuleResult,
    ModuleScore,
    Probe,
    ProbeResult,
    Severity,
)
from tests.conftest import make_probe_result, make_module_result


# ---------------------------------------------------------------------------
# Tests: ModuleScore.grade_from_score
# ---------------------------------------------------------------------------

class TestGradeFromScore:
    """grade_from_score boundary tests."""

    @pytest.mark.parametrize(
        "score, critical, expected",
        [
            # A grade: >= 0.90
            (1.0, 0, "A"),
            (0.95, 0, "A"),
            (0.90, 0, "A"),
            # B grade: >= 0.75
            (0.899, 0, "B"),
            (0.85, 0, "B"),
            (0.75, 0, "B"),
            # C grade: >= 0.60
            (0.749, 0, "C"),
            (0.70, 0, "C"),
            (0.60, 0, "C"),
            # D grade: >= 0.40
            (0.599, 0, "D"),
            (0.50, 0, "D"),
            (0.40, 0, "D"),
            # F grade: < 0.40
            (0.399, 0, "F"),
            (0.1, 0, "F"),
            (0.0, 0, "F"),
        ],
    )
    def test_boundaries(self, score, critical, expected):
        assert ModuleScore.grade_from_score(score, critical) == expected

    def test_critical_failures_force_F(self):
        """Any critical failure should return F regardless of score."""
        assert ModuleScore.grade_from_score(1.0, critical_failures=1) == "F"
        assert ModuleScore.grade_from_score(0.95, critical_failures=1) == "F"
        assert ModuleScore.grade_from_score(0.5, critical_failures=3) == "F"

    def test_zero_critical_no_penalty(self):
        assert ModuleScore.grade_from_score(0.95, critical_failures=0) == "A"

    def test_exact_boundaries(self):
        """Exact boundary values fall into the correct grade."""
        assert ModuleScore.grade_from_score(0.90, 0) == "A"
        assert ModuleScore.grade_from_score(0.75, 0) == "B"
        assert ModuleScore.grade_from_score(0.60, 0) == "C"
        assert ModuleScore.grade_from_score(0.40, 0) == "D"

    def test_just_below_boundaries(self):
        assert ModuleScore.grade_from_score(0.8999, 0) == "B"
        assert ModuleScore.grade_from_score(0.7499, 0) == "C"
        assert ModuleScore.grade_from_score(0.5999, 0) == "D"
        assert ModuleScore.grade_from_score(0.3999, 0) == "F"


# ---------------------------------------------------------------------------
# Tests: ProbeResult
# ---------------------------------------------------------------------------

class TestProbeResult:
    """ProbeResult creation and serialization."""

    def test_creation_with_defaults(self):
        pr = ProbeResult(
            probe_id="p1",
            probe_name="Test",
            passed=True,
            score=1.0,
            severity=Severity.MEDIUM,
            model_output="output",
            expected="expected",
            reason="all good",
        )
        assert pr.probe_id == "p1"
        assert pr.passed is True
        assert pr.duration_s == 0.0
        assert pr.turn_count == 1
        assert pr.meta == {}

    def test_creation_with_all_fields(self):
        pr = ProbeResult(
            probe_id="p2",
            probe_name="Full",
            passed=False,
            score=0.3,
            severity=Severity.CRITICAL,
            model_output="bad output",
            expected="good output",
            reason="failed hard",
            duration_s=2.5,
            turn_count=3,
            meta={"extra": True},
        )
        assert pr.score == 0.3
        assert pr.severity == Severity.CRITICAL
        assert pr.duration_s == 2.5
        assert pr.turn_count == 3
        assert pr.meta == {"extra": True}

    def test_to_dict_keys(self):
        pr = make_probe_result()
        d = pr.to_dict()
        expected_keys = {
            "probe_id", "probe_name", "passed", "score",
            "severity", "model_output", "expected", "reason",
            "duration_s", "turn_count",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_score_rounded(self):
        pr = make_probe_result(score=0.33333)
        d = pr.to_dict()
        assert d["score"] == 0.333

    def test_to_dict_truncates_output(self):
        pr = make_probe_result(model_output="x" * 1000)
        d = pr.to_dict()
        assert len(d["model_output"]) == 500

    def test_severity_values(self):
        """All severity enum values are valid."""
        pr_crit = make_probe_result(severity=Severity.CRITICAL)
        pr_high = make_probe_result(severity=Severity.HIGH)
        pr_med = make_probe_result(severity=Severity.MEDIUM)
        pr_low = make_probe_result(severity=Severity.LOW)
        assert pr_crit.to_dict()["severity"] == "critical"
        assert pr_high.to_dict()["severity"] == "high"
        assert pr_med.to_dict()["severity"] == "medium"
        assert pr_low.to_dict()["severity"] == "low"


# ---------------------------------------------------------------------------
# Tests: Severity enum
# ---------------------------------------------------------------------------

class TestSeverityEnum:
    def test_values(self):
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.LOW.value == "low"

    def test_is_str_enum(self):
        assert isinstance(Severity.CRITICAL, str)
        assert Severity.CRITICAL == "critical"


# ---------------------------------------------------------------------------
# Tests: ModuleResult
# ---------------------------------------------------------------------------

class TestModuleResult:
    """ModuleResult aggregation properties."""

    def test_empty_result(self):
        mr = make_module_result(probe_results=[])
        assert mr.total_probes == 0
        assert mr.passed_probes == 0
        assert mr.failed_probes == 0
        assert mr.pass_rate == 0.0

    def test_all_passed(self):
        probes = [make_probe_result(passed=True) for _ in range(5)]
        mr = make_module_result(probe_results=probes)
        assert mr.total_probes == 5
        assert mr.passed_probes == 5
        assert mr.failed_probes == 0
        assert mr.pass_rate == 1.0

    def test_all_failed(self):
        probes = [make_probe_result(passed=False, score=0.0) for _ in range(3)]
        mr = make_module_result(probe_results=probes)
        assert mr.total_probes == 3
        assert mr.passed_probes == 0
        assert mr.failed_probes == 3
        assert mr.pass_rate == 0.0

    def test_mixed_results(self):
        probes = [
            make_probe_result(probe_id="p1", passed=True),
            make_probe_result(probe_id="p2", passed=False, score=0.0),
            make_probe_result(probe_id="p3", passed=True),
        ]
        mr = make_module_result(probe_results=probes)
        assert mr.total_probes == 3
        assert mr.passed_probes == 2
        assert mr.failed_probes == 1
        assert mr.pass_rate == pytest.approx(2 / 3)

    def test_to_dict_structure(self):
        probes = [make_probe_result()]
        mr = make_module_result(module_name="MY_MODULE", probe_results=probes)
        d = mr.to_dict()
        assert d["module"] == "MY_MODULE"
        assert d["pass_rate"] == 1.0
        assert d["passed"] == 1
        assert d["total"] == 1
        assert isinstance(d["probes"], list)
        assert len(d["probes"]) == 1

    def test_to_dict_with_error(self):
        mr = ModuleResult(
            module_name="ERR",
            module_version="1.0",
            model="m",
            error="Could not connect",
        )
        d = mr.to_dict()
        assert d["error"] == "Could not connect"


# ---------------------------------------------------------------------------
# Tests: ModuleScore
# ---------------------------------------------------------------------------

class TestModuleScore:
    def test_to_dict_structure(self):
        ms = ModuleScore(
            module_name="TEST",
            score=0.85,
            grade="B",
            passed=8,
            failed=2,
            total=10,
            critical_failures=0,
            high_failures=1,
            summary="Good results",
        )
        d = ms.to_dict()
        assert d["module"] == "TEST"
        assert d["score"] == 0.85
        assert d["grade"] == "B"
        assert d["passed"] == 8
        assert d["failed"] == 2
        assert d["total"] == 10
        assert d["critical_failures"] == 0
        assert d["high_failures"] == 1
        assert d["summary"] == "Good results"

    def test_score_rounded_in_dict(self):
        ms = ModuleScore(
            module_name="X", score=0.33333, grade="F",
            passed=0, failed=1, total=1,
            critical_failures=0, high_failures=0, summary="",
        )
        assert ms.to_dict()["score"] == 0.333


# ---------------------------------------------------------------------------
# Tests: Probe dataclass
# ---------------------------------------------------------------------------

class TestProbe:
    def test_defaults(self):
        p = Probe(id="p1", name="Test", description="A probe")
        assert p.severity == Severity.MEDIUM
        assert p.tags == []
        assert p.messages == []
        assert p.expected == ""
        assert p.meta == {}

    def test_full_construction(self):
        p = Probe(
            id="p2",
            name="Full probe",
            description="Tests everything",
            severity=Severity.CRITICAL,
            tags=["safety", "boundary"],
            messages=[("user", "hello")],
            expected="A safe response",
            meta={"key": "val"},
        )
        assert p.severity == Severity.CRITICAL
        assert len(p.tags) == 2
        assert p.messages[0] == ("user", "hello")
        assert p.meta["key"] == "val"
