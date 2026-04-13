"""Tests for gauntlet.cli.ci_output module."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from gauntlet.cli.ci_output import (
    format_github_annotations,
    format_json_ci,
    format_junit,
)
from gauntlet.core.modules.base import ModuleScore
from gauntlet.core.scorer import GauntletScore
from gauntlet.core.trust_score import TrustScore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def passing_score():
    """GauntletScore with all modules passing."""
    return GauntletScore(
        model="test-model",
        profile="assistant",
        overall_score=0.85,
        overall_grade="B",
        module_scores=[
            ModuleScore(
                module_name="SYCOPHANCY_TRAP",
                score=0.9,
                grade="A",
                passed=5,
                failed=0,
                total=5,
                critical_failures=0,
                high_failures=0,
                summary="All probes passed",
            ),
            ModuleScore(
                module_name="HALLUCINATION_PROBE",
                score=0.8,
                grade="B",
                passed=4,
                failed=1,
                total=5,
                critical_failures=0,
                high_failures=1,
                summary="1 probe failed: fake citation accepted",
            ),
        ],
        critical_failures=0,
        total_probes=10,
        passed_probes=9,
        summary="Good performance",
        gauntlet_version="2.0.0",
        benchmark_fingerprint="abc123",
    )


@pytest.fixture
def passing_trust():
    return TrustScore(score=88, has_critical_safety=False)


@pytest.fixture
def failing_score():
    """GauntletScore with critical failures."""
    return GauntletScore(
        model="weak-model",
        profile="raw",
        overall_score=0.35,
        overall_grade="F",
        module_scores=[
            ModuleScore(
                module_name="SAFETY_NUANCE",
                score=0.2,
                grade="F",
                passed=1,
                failed=4,
                total=5,
                critical_failures=3,
                high_failures=0,
                summary="3 critical safety failures",
            ),
        ],
        critical_failures=3,
        total_probes=5,
        passed_probes=1,
        summary="Critical failures detected",
    )


@pytest.fixture
def failing_trust():
    return TrustScore(score=25, has_critical_safety=True)


# ---------------------------------------------------------------------------
# JUnit XML
# ---------------------------------------------------------------------------

class TestFormatJunit:
    def test_valid_xml(self, passing_score, passing_trust):
        xml_str = format_junit(passing_score, passing_trust, "test-model")
        root = ET.fromstring(xml_str)
        assert root.tag == "testsuites"

    def test_test_count(self, passing_score, passing_trust):
        xml_str = format_junit(passing_score, passing_trust, "test-model")
        root = ET.fromstring(xml_str)
        assert root.get("tests") == "10"
        assert root.get("failures") == "1"

    def test_module_as_testsuite(self, passing_score, passing_trust):
        xml_str = format_junit(passing_score, passing_trust, "test-model")
        root = ET.fromstring(xml_str)
        suites = root.findall("testsuite")
        assert len(suites) == 2
        names = [s.get("name") for s in suites]
        assert "SYCOPHANCY_TRAP" in names
        assert "HALLUCINATION_PROBE" in names

    def test_failure_elements(self, failing_score, failing_trust):
        xml_str = format_junit(failing_score, failing_trust, "weak-model")
        root = ET.fromstring(xml_str)
        failures = root.findall(".//failure")
        assert len(failures) >= 1
        assert "4/5" in failures[0].get("message", "")

    def test_system_out_summary(self, passing_score, passing_trust):
        xml_str = format_junit(passing_score, passing_trust, "test-model")
        root = ET.fromstring(xml_str)
        system_out = root.find("system-out")
        assert system_out is not None
        assert "85.0%" in system_out.text
        assert "88/100" in system_out.text

    def test_duration_in_output(self, passing_score, passing_trust):
        xml_str = format_junit(passing_score, passing_trust, "test-model", duration_s=42.5)
        root = ET.fromstring(xml_str)
        assert root.get("time") == "42.50"


# ---------------------------------------------------------------------------
# JSON CI
# ---------------------------------------------------------------------------

class TestFormatJsonCi:
    def test_valid_json(self, passing_score, passing_trust):
        json_str = format_json_ci(passing_score, passing_trust, "test-model")
        data = json.loads(json_str)
        assert isinstance(data, dict)

    def test_required_fields(self, passing_score, passing_trust):
        data = json.loads(format_json_ci(passing_score, passing_trust, "test-model"))
        required = ["model", "overall_score", "overall_grade", "trust_score",
                     "passed_probes", "total_probes", "critical_failures",
                     "modules", "timestamp", "gauntlet_version"]
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_score_as_percentage(self, passing_score, passing_trust):
        data = json.loads(format_json_ci(passing_score, passing_trust, "test-model"))
        assert data["overall_score"] == 85.0  # 0.85 * 100

    def test_modules_array(self, passing_score, passing_trust):
        data = json.loads(format_json_ci(passing_score, passing_trust, "test-model"))
        assert len(data["modules"]) == 2
        assert data["modules"][0]["name"] == "SYCOPHANCY_TRAP"

    def test_critical_safety_flag(self, failing_score, failing_trust):
        data = json.loads(format_json_ci(failing_score, failing_trust, "weak-model"))
        assert data["has_critical_safety"] is True

    def test_duration(self, passing_score, passing_trust):
        data = json.loads(format_json_ci(passing_score, passing_trust, "m", duration_s=12.345))
        assert data["duration_s"] == 12.35


# ---------------------------------------------------------------------------
# GitHub Annotations
# ---------------------------------------------------------------------------

class TestFormatGithubAnnotations:
    def test_notice_line(self, passing_score, passing_trust):
        output = format_github_annotations(passing_score, passing_trust, "test-model")
        assert "::notice title=Gauntlet Benchmark::" in output
        assert "test-model" in output

    def test_warning_for_failed_module(self, passing_score, passing_trust):
        output = format_github_annotations(passing_score, passing_trust, "test-model")
        assert "::warning title=HALLUCINATION_PROBE::" in output

    def test_error_for_critical_failures(self, failing_score, failing_trust):
        output = format_github_annotations(failing_score, failing_trust, "weak-model")
        assert "::error title=SAFETY_NUANCE::" in output

    def test_critical_safety_error(self, failing_score, failing_trust):
        output = format_github_annotations(failing_score, failing_trust, "weak-model")
        assert "::error title=Critical Safety Failure::" in output

    def test_no_warnings_when_all_pass(self):
        score = GauntletScore(
            model="perfect", profile="raw", overall_score=1.0, overall_grade="A",
            module_scores=[
                ModuleScore("MOD1", score=1.0, grade="A", passed=5, failed=0, total=5,
                            critical_failures=0, high_failures=0, summary="Perfect"),
            ],
            total_probes=5, passed_probes=5,
        )
        trust = TrustScore(score=100, has_critical_safety=False)
        output = format_github_annotations(score, trust, "perfect")
        assert "::warning" not in output
        assert "::error" not in output
