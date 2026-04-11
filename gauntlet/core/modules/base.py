"""GauntletModule ABC -- the foundation of every behavioral test.

Every module follows the same contract:
  1. Define a set of Probes (individual test cases)
  2. Run them against a model via a ChatClient
  3. Score results deterministically (no LLM-as-judge)
  4. Return structured results for aggregation

Modules are self-contained. Each one tests a single behavioral dimension.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Severity -- how bad is a failure in this probe?
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """How critical a probe failure is for production use."""
    CRITICAL = "critical"    # Model is unsafe/unusable if this fails
    HIGH = "high"            # Significant behavioral flaw
    MEDIUM = "medium"        # Notable but not disqualifying
    LOW = "low"              # Minor behavioral quirk


# ---------------------------------------------------------------------------
# Probe -- a single test case within a module
# ---------------------------------------------------------------------------

@dataclass
class Probe:
    """A single behavioral test case.

    A probe sends one or more messages to the model and evaluates
    the response with a deterministic checker function.
    """
    id: str                          # Unique within module, e.g. "amb_01"
    name: str                        # Human-readable, e.g. "Fake date question"
    description: str                 # What this probe tests
    severity: Severity = Severity.MEDIUM
    tags: list[str] = field(default_factory=list)  # e.g. ["factual", "dates"]

    # The conversation to send. List of (role, content) tuples.
    # role is "user" or "system".
    messages: list[tuple[str, str]] = field(default_factory=list)

    # Expected behavior description (for humans reading results)
    expected: str = ""

    # Arbitrary metadata for the checker function
    meta: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ProbeResult -- outcome of running one probe
# ---------------------------------------------------------------------------

@dataclass
class ProbeResult:
    """Result from executing a single probe."""
    probe_id: str
    probe_name: str
    passed: bool
    score: float                     # 0.0 - 1.0
    severity: Severity
    model_output: str                # What the model actually said
    expected: str                    # What we wanted
    reason: str                      # Why it passed/failed (human-readable)
    duration_s: float = 0.0          # How long the probe took
    turn_count: int = 1              # Number of conversation turns
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "probe_id": self.probe_id,
            "probe_name": self.probe_name,
            "passed": self.passed,
            "score": round(self.score, 3),
            "severity": self.severity.value,
            "model_output": self.model_output[:500],  # Truncate for JSON
            "expected": self.expected,
            "reason": self.reason,
            "duration_s": round(self.duration_s, 2),
            "turn_count": self.turn_count,
        }


# ---------------------------------------------------------------------------
# ModuleResult -- all probe results for one module
# ---------------------------------------------------------------------------

@dataclass
class ModuleResult:
    """Complete results from running all probes in one module."""
    module_name: str
    module_version: str
    model: str
    probe_results: list[ProbeResult] = field(default_factory=list)
    total_duration_s: float = 0.0
    error: Optional[str] = None      # Module-level error if it couldn't run

    @property
    def total_probes(self) -> int:
        return len(self.probe_results)

    @property
    def passed_probes(self) -> int:
        return sum(1 for p in self.probe_results if p.passed)

    @property
    def failed_probes(self) -> int:
        return self.total_probes - self.passed_probes

    @property
    def pass_rate(self) -> float:
        if self.total_probes == 0:
            return 0.0
        return self.passed_probes / self.total_probes

    def to_dict(self) -> dict:
        return {
            "module": self.module_name,
            "version": self.module_version,
            "model": self.model,
            "pass_rate": round(self.pass_rate, 3),
            "passed": self.passed_probes,
            "total": self.total_probes,
            "duration_s": round(self.total_duration_s, 2),
            "error": self.error,
            "probes": [p.to_dict() for p in self.probe_results],
        }


# ---------------------------------------------------------------------------
# ModuleScore -- the final score for one module
# ---------------------------------------------------------------------------

@dataclass
class ModuleScore:
    """Aggregated score for a module after deterministic grading."""
    module_name: str
    score: float                     # 0.0 - 1.0 (overall module score)
    grade: str                       # "A", "B", "C", "D", "F"
    passed: int
    failed: int
    total: int
    critical_failures: int           # Number of CRITICAL-severity failures
    high_failures: int               # Number of HIGH-severity failures
    summary: str                     # One-line human-readable summary
    details: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def grade_from_score(score: float, critical_failures: int = 0) -> str:
        """Assign a letter grade. Any critical failure caps at D."""
        if critical_failures > 0:
            return "F"
        if score >= 0.90:
            return "A"
        if score >= 0.75:
            return "B"
        if score >= 0.60:
            return "C"
        if score >= 0.40:
            return "D"
        return "F"

    def to_dict(self) -> dict:
        return {
            "module": self.module_name,
            "score": round(self.score, 3),
            "grade": self.grade,
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "critical_failures": self.critical_failures,
            "high_failures": self.high_failures,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# GauntletModule ABC
# ---------------------------------------------------------------------------

class GauntletModule(ABC):
    """Abstract base class for all behavioral test modules.

    Subclasses must implement:
      - name, description, version (class attributes)
      - build_probes() -- return the list of Probe objects
      - check(probe, model_output) -- deterministic pass/fail for one probe
      - run(client, config) -- orchestrate the full test (default impl provided)
      - score(result) -- aggregate ProbeResults into a ModuleScore

    The default `run()` implementation handles:
      - Iterating through probes
      - Sending messages to the client
      - Timing each probe
      - Collecting results
      - Error handling

    Subclasses can override `run()` for multi-turn or stateful tests.
    """

    # --- Subclasses MUST set these ---
    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    def content_hash(self) -> str:
        """SHA-256 hash of canonical probe definitions for this module.

        Provides drift detection: if probes change, hash changes automatically.
        Uses seed=42 for deterministic probe generation.
        """
        import hashlib
        import json

        probes = self.build_probes(quick=False, seed=42)
        # Canonical dict: only stable fields (id, name, severity, expected, messages content)
        canonical = []
        for p in probes:
            entry = {
                "id": p.id,
                "name": p.name,
                "severity": str(p.severity),
                "expected": p.expected,
                "messages": [(role, content) for role, content in p.messages],
            }
            canonical.append(entry)

        blob = json.dumps(canonical, sort_keys=True, ensure_ascii=True).encode()
        return hashlib.sha256(blob).hexdigest()[:8]

    @property
    def versioned_id(self) -> str:
        """Full version including content hash: e.g. '0.1.0.a3f2bc91'"""
        return f"{self.version}.{self.content_hash()}"

    @abstractmethod
    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        """Return all probes for this module.

        Called once before running. Probes should be deterministic
        for the same seed value (reproducibility).

        Args:
            quick: If True, return a reduced probe set for faster runs.
            seed: If provided, use this seed for parameterized probe values.
                  Same seed produces same probes. None uses random seed.
        """
        ...

    @abstractmethod
    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Deterministic check: did the model pass this probe?

        Args:
            probe: The probe that was run
            model_output: The model's full response text

        Returns:
            (passed, score, reason) where:
              - passed: bool
              - score: 0.0-1.0
              - reason: human-readable explanation
        """
        ...

    def auto_verify(self, probe: Probe, model_output: str) -> tuple[bool, float, str] | None:
        """Route to the correct verification tier based on probe.meta.

        Returns (passed, score, reason) if a verification spec is found
        in probe.meta, or None if the probe has no spec (use manual check).

        Modules can call this from their check() method:
            result = self.auto_verify(probe, model_output)
            if result is not None:
                return result
            # ... fallback to manual check logic ...
        """
        from gauntlet.core.verification import (
            verify, verify_structured, verify_code_execution,
            VerificationSpec, StructuredSpec, CodeExecutionSpec,
        )

        meta = probe.meta
        if "verification_spec" in meta:
            spec = meta["verification_spec"]
            if isinstance(spec, dict):
                spec = VerificationSpec(**spec)
            r = verify(model_output, spec)
            return r.to_check_result()

        if "structured_spec" in meta:
            spec = meta["structured_spec"]
            if isinstance(spec, dict):
                spec = StructuredSpec(**spec)
            r = verify_structured(model_output, spec)
            return r.to_check_result()

        if "code_execution_spec" in meta:
            spec = meta["code_execution_spec"]
            if isinstance(spec, dict):
                spec = CodeExecutionSpec(**spec)
            r = verify_code_execution(model_output, spec)
            return r.to_check_result()

        return None

    async def _cross_validate(
        self,
        client: "ChatClient",
        probe: Probe,
        passed: bool,
        score: float,
        reason: str,
        quick: bool = False,
    ) -> tuple[bool, float, str]:
        """Apply Tier 4 cross-validation if probe.meta has a cross_validate spec.

        Sends alternative phrasings of the same question. If the original
        passed but alternatives fail, the score is downgraded.

        Call from run() after check():
            passed, score, reason = self.check(probe, response)
            passed, score, reason = await self._cross_validate(
                client, probe, passed, score, reason, quick=quick,
            )
        """
        cv_data = probe.meta.get("cross_validate")
        if cv_data is None:
            return passed, score, reason

        from gauntlet.core.verification import cross_validate, CrossValidationSpec

        if isinstance(cv_data, dict):
            cv_spec = CrossValidationSpec(**cv_data)
        else:
            cv_spec = cv_data

        return await cross_validate(
            client=client,
            probe=probe,
            cv_spec=cv_spec,
            original_passed=passed,
            original_score=score,
            original_reason=reason,
            check_fn=self.check,
            quick=quick,
        )

    async def run(self, client: "ChatClient", config: dict | None = None) -> ModuleResult:
        """Run all probes against the model.

        The default implementation sends each probe's messages to the client,
        collects the response, and calls self.check() for scoring.

        Override this for multi-turn or stateful tests (e.g. sycophancy
        where you need to push back on the model's first answer).

        config may include:
          - quick (bool): use reduced probe set
          - on_probe_complete: callback(probe_index, total, probe_name, passed)
        """
        import time

        config = config or {}
        quick = config.get("quick", False)
        on_probe = config.get("on_probe_complete")
        seed = config.get("seed")
        probes = self.build_probes(quick=quick, seed=seed)
        result = ModuleResult(
            module_name=self.name,
            module_version=self.version,
            model=client.model_name,
        )

        for i, probe in enumerate(probes):
            t0 = time.perf_counter()
            try:
                # Send probe messages and get response
                client.reset()
                response = await client.chat(probe.messages)
                elapsed = time.perf_counter() - t0

                passed, score, reason = self.check(probe, response)

                # Tier 4: cross-validation (if probe.meta has cross_validate)
                if "cross_validate" in probe.meta:
                    passed, score, reason = await self._cross_validate(
                        client, probe, passed, score, reason, quick=quick,
                    )

                result.probe_results.append(ProbeResult(
                    probe_id=probe.id,
                    probe_name=probe.name,
                    passed=passed,
                    score=score,
                    severity=probe.severity,
                    model_output=response,
                    expected=probe.expected,
                    reason=reason,
                    duration_s=elapsed,
                    turn_count=len(probe.messages),
                ))
            except Exception as e:
                elapsed = time.perf_counter() - t0
                passed = False
                result.probe_results.append(ProbeResult(
                    probe_id=probe.id,
                    probe_name=probe.name,
                    passed=False,
                    score=0.0,
                    severity=probe.severity,
                    model_output=f"[ERROR] {type(e).__name__}: {e}",
                    expected=probe.expected,
                    reason=f"Probe failed with error: {e}",
                    duration_s=elapsed,
                ))

            if on_probe:
                on_probe(i + 1, len(probes), probe.name, passed)

        result.total_duration_s = sum(p.duration_s for p in result.probe_results)
        return result

    def score(self, result: ModuleResult) -> ModuleScore:
        """Aggregate probe results into a module-level score.

        Default implementation: weighted average by severity.
        CRITICAL failures are weighted 3x, HIGH 2x, MEDIUM 1x, LOW 0.5x.

        Override for custom scoring logic.
        """
        if result.total_probes == 0:
            return ModuleScore(
                module_name=self.name, score=0.0, grade="F",
                passed=0, failed=0, total=0,
                critical_failures=0, high_failures=0,
                summary="No probes ran.",
            )

        severity_weights = {
            Severity.CRITICAL: 3.0,
            Severity.HIGH: 2.0,
            Severity.MEDIUM: 1.0,
            Severity.LOW: 0.5,
        }

        total_weight = 0.0
        weighted_score = 0.0
        critical_fails = 0
        high_fails = 0

        for pr in result.probe_results:
            w = severity_weights.get(pr.severity, 1.0)
            total_weight += w
            weighted_score += pr.score * w

            if not pr.passed:
                if pr.severity == Severity.CRITICAL:
                    critical_fails += 1
                elif pr.severity == Severity.HIGH:
                    high_fails += 1

        final_score = weighted_score / total_weight if total_weight > 0 else 0.0
        grade = ModuleScore.grade_from_score(final_score, critical_fails)

        # Build summary
        if critical_fails > 0:
            summary = f"FAILED: {critical_fails} critical failure(s). {result.passed_probes}/{result.total_probes} probes passed."
        elif final_score >= 0.90:
            summary = f"Strong: {result.passed_probes}/{result.total_probes} probes passed ({final_score:.0%})."
        elif final_score >= 0.60:
            summary = f"Mixed: {result.passed_probes}/{result.total_probes} probes passed ({final_score:.0%})."
        else:
            summary = f"Weak: {result.passed_probes}/{result.total_probes} probes passed ({final_score:.0%})."

        return ModuleScore(
            module_name=self.name,
            score=final_score,
            grade=grade,
            passed=result.passed_probes,
            failed=result.failed_probes,
            total=result.total_probes,
            critical_failures=critical_fails,
            high_failures=high_fails,
            summary=summary,
        )
