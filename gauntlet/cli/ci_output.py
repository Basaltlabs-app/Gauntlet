"""CI/CD output formatters for Gauntlet benchmark results.

Generates machine-readable output for CI pipelines:
  - JUnit XML for test reporters (GitHub Actions, Jenkins, GitLab CI)
  - JSON for custom pipeline consumption
  - GitHub Actions annotations
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

from gauntlet.core.scorer import GauntletScore
from gauntlet.core.trust_score import TrustScore


def format_junit(
    score: GauntletScore,
    trust: TrustScore,
    model: str,
    duration_s: float = 0.0,
) -> str:
    """Generate JUnit XML from benchmark results.

    Each module becomes a <testsuite>, each probe becomes a <testcase>.
    Failed probes include <failure> elements with reason text.
    """
    testsuites = ET.Element("testsuites")
    testsuites.set("name", f"Gauntlet Benchmark - {model}")
    testsuites.set("tests", str(score.total_probes))
    testsuites.set("failures", str(score.total_probes - score.passed_probes))
    testsuites.set("time", f"{duration_s:.2f}")

    for ms in score.module_scores:
        suite = ET.SubElement(testsuites, "testsuite")
        suite.set("name", ms.module_name)
        suite.set("tests", str(ms.total))
        suite.set("failures", str(ms.failed))
        suite.set("time", "0")

        # Properties
        props = ET.SubElement(suite, "properties")
        prop = ET.SubElement(props, "property")
        prop.set("name", "grade")
        prop.set("value", ms.grade)
        prop = ET.SubElement(props, "property")
        prop.set("name", "score")
        prop.set("value", f"{ms.score:.2f}")

        # We don't have individual probe results in ModuleScore,
        # so create a single testcase per module
        tc = ET.SubElement(suite, "testcase")
        tc.set("name", ms.module_name)
        tc.set("classname", f"gauntlet.{ms.module_name}")
        tc.set("time", "0")

        if ms.failed > 0:
            failure = ET.SubElement(tc, "failure")
            failure.set("message", f"{ms.failed}/{ms.total} probes failed")
            failure.set("type", "BenchmarkFailure")
            failure.text = ms.summary

    # System out with overall summary
    system_out = ET.SubElement(testsuites, "system-out")
    system_out.text = (
        f"Overall: {score.overall_score:.1%} ({score.overall_grade}) | "
        f"Trust: {trust.score}/100 | "
        f"Probes: {score.passed_probes}/{score.total_probes} passed"
    )

    return ET.tostring(testsuites, encoding="unicode", xml_declaration=True)


def format_json_ci(
    score: GauntletScore,
    trust: TrustScore,
    model: str,
    duration_s: float = 0.0,
) -> str:
    """Generate CI-friendly JSON output."""
    return json.dumps({
        "model": model,
        "overall_score": round(score.overall_score * 100, 1),
        "overall_grade": score.overall_grade,
        "trust_score": trust.score,
        "passed_probes": score.passed_probes,
        "total_probes": score.total_probes,
        "critical_failures": score.critical_failures,
        "has_critical_safety": trust.has_critical_safety,
        "profile": score.profile,
        "gauntlet_version": score.gauntlet_version,
        "benchmark_fingerprint": score.benchmark_fingerprint,
        "duration_s": round(duration_s, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modules": [
            {
                "name": ms.module_name,
                "score": round(ms.score, 3),
                "grade": ms.grade,
                "passed": ms.passed,
                "failed": ms.failed,
                "total": ms.total,
                "critical_failures": ms.critical_failures,
            }
            for ms in score.module_scores
        ],
    }, indent=2)


def format_github_annotations(
    score: GauntletScore,
    trust: TrustScore,
    model: str,
) -> str:
    """Generate GitHub Actions workflow annotations."""
    lines = []

    # Summary as notice
    lines.append(
        f"::notice title=Gauntlet Benchmark::"
        f"Model: {model} | Score: {score.overall_score:.1%} ({score.overall_grade}) | "
        f"Trust: {trust.score}/100 | Probes: {score.passed_probes}/{score.total_probes}"
    )

    # Failed modules as warnings/errors
    for ms in score.module_scores:
        if ms.critical_failures > 0:
            lines.append(f"::error title={ms.module_name}::{ms.summary}")
        elif ms.failed > 0:
            lines.append(f"::warning title={ms.module_name}::{ms.summary}")

    # Critical safety as error
    if trust.has_critical_safety:
        lines.append("::error title=Critical Safety Failure::Model failed critical safety probes")

    return "\n".join(lines)
