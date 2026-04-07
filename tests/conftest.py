"""Shared test fixtures for Gauntlet tests."""
from __future__ import annotations

import pytest
from gauntlet.core.modules.base import (
    ModuleResult,
    ProbeResult,
    Severity,
)


def make_probe_result(
    probe_id: str = "test_01",
    probe_name: str = "Test probe",
    passed: bool = True,
    score: float = 1.0,
    severity: Severity = Severity.MEDIUM,
    model_output: str = "Test output",
    expected: str = "Expected output",
    reason: str = "Test reason",
) -> ProbeResult:
    """Factory for ProbeResult with sensible defaults."""
    return ProbeResult(
        probe_id=probe_id,
        probe_name=probe_name,
        passed=passed,
        score=score,
        severity=severity,
        model_output=model_output,
        expected=expected,
        reason=reason,
    )


def make_module_result(
    module_name: str = "TEST_MODULE",
    model: str = "test-model",
    probe_results: list[ProbeResult] | None = None,
) -> ModuleResult:
    """Factory for ModuleResult with sensible defaults."""
    return ModuleResult(
        module_name=module_name,
        module_version="1.0.0",
        model=model,
        probe_results=probe_results or [],
    )
