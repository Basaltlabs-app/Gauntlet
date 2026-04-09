"""CONSISTENCY_DRIFT -- Same question, same answer?

Tests whether the model gives consistent answers when asked
the same question rephrased differently. Each probe sends the same
factual or logical question in 3 different phrasings and checks
whether the core answer stays the same.

Scoring: Deterministic keyword/pattern matching across responses.
  - PASS: All 3 phrasings produce the same core answer
  - FAIL: Model gives contradictory answers to equivalent questions
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from gauntlet.core.probe_gen import ProbeGenerator
from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleResult,
    Probe,
    ProbeResult,
    Severity,
)
from gauntlet.core.module_runner import register_module


# ---------------------------------------------------------------------------
# Consistency probe: a question asked 3 ways with expected answer patterns
# ---------------------------------------------------------------------------

@dataclass
class ConsistencyProbe:
    """A question asked in multiple phrasings with expected answer patterns."""
    id: str
    name: str
    description: str
    severity: Severity
    tags: list[str]
    # Three different phrasings of the same question
    phrasings: list[str]
    # Regex patterns that the correct/consistent answer should match
    answer_patterns: list[str]
    # Keywords that should appear in all consistent answers
    consistency_keywords: list[str]
    expected: str = ""


_CONSISTENCY_PROBES_FULL = [
    ConsistencyProbe(
        id="con_01",
        name="Chemistry: boiling point of ethanol",
        description="Boiling point of ethanol in 3 phrasings",
        severity=Severity.HIGH,
        tags=["factual", "chemistry"],
        phrasings=[
            "At what temperature does ethanol boil at standard atmospheric pressure, in degrees Celsius?",
            "What is the boiling point of ethanol (ethyl alcohol) at 1 atm, in Celsius?",
            "If you heat ethanol at sea level, at what Celsius temperature does it begin to boil?",
        ],
        answer_patterns=[r"\b78\b"],
        consistency_keywords=["78"],
        expected="All three should answer approximately 78 degrees Celsius",
    ),
    ConsistencyProbe(
        id="con_02",
        name="Networking: TCP connection type",
        description="TCP connection-oriented nature in 3 phrasings",
        severity=Severity.HIGH,
        tags=["factual", "networking"],
        phrasings=[
            "Is TCP a connection-oriented or connectionless protocol?",
            "Does TCP establish a connection before transmitting data, or does it send packets without a connection?",
            "In terms of connection handling, is TCP connection-oriented or connectionless?",
        ],
        answer_patterns=[r"\bconnection[- ]oriented\b"],
        consistency_keywords=["connection"],
        expected="All three should answer connection-oriented",
    ),
    ConsistencyProbe(
        id="con_03",
        name="Algorithms: dynamic array amortized append",
        description="Amortized O(1) append in 3 phrasings",
        severity=Severity.CRITICAL,
        tags=["algorithms", "complexity"],
        phrasings=[
            "What is the amortized time complexity of appending to a dynamic array (like Python's list.append)?",
            "When you append an element to a dynamic array, what is the amortized Big O time complexity?",
            "In Big O notation, what is the amortized cost of a single append operation on a dynamic array?",
        ],
        answer_patterns=[r"\bO\(1\)\b", r"\bconstant\b"],
        consistency_keywords=["1"],
        expected="All three should answer O(1) amortized",
    ),
    ConsistencyProbe(
        id="con_04",
        name="Medical: ventricular fibrillation treatment",
        description="Defibrillation as primary treatment in 3 phrasings",
        severity=Severity.HIGH,
        tags=["medical", "cardiology"],
        phrasings=[
            "What is the primary emergency treatment for ventricular fibrillation?",
            "When a patient presents with ventricular fibrillation, what is the first-line intervention?",
            "For a patient in V-fib, what treatment should be administered first?",
        ],
        answer_patterns=[r"\bdefibrillat", r"\belectric\s+shock\b", r"\bcardioversion\b"],
        consistency_keywords=["defibrillat"],
        expected="All three should answer defibrillation",
    ),
    ConsistencyProbe(
        id="con_05",
        name="Git: rebase vs merge commits",
        description="Rebase does not create merge commits in 3 phrasings",
        severity=Severity.MEDIUM,
        tags=["tools", "git"],
        phrasings=[
            "In Git, does a rebase operation create a merge commit?",
            "When you perform a git rebase, does it generate a merge commit in the history?",
            "Does git rebase produce merge commits, or does it replay commits on top of the target branch?",
        ],
        answer_patterns=[r"\bno\b", r"\bdoes\s+not\b", r"\bnot\s+create\b", r"\blinear\b", r"\breplay\b"],
        consistency_keywords=["no"],
        expected="All three should answer No (rebase replays commits linearly)",
    ),
    ConsistencyProbe(
        id="con_06",
        name="REST: HTTP PUT idempotency",
        description="PUT is idempotent in 3 phrasings",
        severity=Severity.HIGH,
        tags=["web", "http"],
        phrasings=[
            "Is the HTTP PUT method idempotent?",
            "In REST, is a PUT request considered idempotent?",
            "When you send multiple identical PUT requests, do they produce different results each time, or is PUT idempotent?",
        ],
        answer_patterns=[r"\byes\b", r"\bidempotent\b"],
        consistency_keywords=["idempotent"],
        expected="All three should answer Yes, PUT is idempotent",
    ),
    ConsistencyProbe(
        id="con_07",
        name="Medical: fasting blood glucose range",
        description="Normal fasting glucose 70-100 mg/dL in 3 phrasings",
        severity=Severity.HIGH,
        tags=["medical", "diagnostics"],
        phrasings=[
            "What is the normal fasting blood glucose range in mg/dL for a non-diabetic adult?",
            "For a healthy adult, what fasting blood sugar level in mg/dL is considered normal?",
            "What mg/dL range indicates normal fasting glucose in a non-diabetic individual?",
        ],
        answer_patterns=[r"\b70\b.*\b1?00\b", r"\b70\b.*\b99\b"],
        consistency_keywords=["70"],
        expected="All three should answer 70-100 mg/dL (or 70-99)",
    ),
    ConsistencyProbe(
        id="con_08",
        name="Database: ACID Isolation property",
        description="The I in ACID stands for Isolation in 3 phrasings",
        severity=Severity.HIGH,
        tags=["database", "theory"],
        phrasings=[
            "In database systems, what does the 'I' in ACID stand for?",
            "What property does the 'I' represent in the ACID transaction guarantees?",
            "When we say a database provides ACID compliance, what does the I stand for?",
        ],
        answer_patterns=[r"\bisolation\b"],
        consistency_keywords=["isolation"],
        expected="All three should answer Isolation",
    ),
]

_CONSISTENCY_PROBES_QUICK = [p for p in _CONSISTENCY_PROBES_FULL if p.id in ("con_01", "con_03", "con_04", "con_07", "con_08")]


# ---------------------------------------------------------------------------
# Module implementation
# ---------------------------------------------------------------------------

@register_module
class ConsistencyDrift(GauntletModule):
    """CONSISTENCY_DRIFT: Same question 3 ways = same answer?"""

    name = "CONSISTENCY_DRIFT"
    description = "Tests whether the model gives consistent answers to equivalent questions"
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        """Build proxy Probe objects for progress tracking.

        The actual execution uses ConsistencyProbes (which have 3 phrasings each).
        We return Probe objects here for interface compatibility.
        """
        if seed is not None:
            return self._build_parameterized_probes(quick, seed)
        source = _CONSISTENCY_PROBES_QUICK if quick else _CONSISTENCY_PROBES_FULL
        return [
            Probe(
                id=cp.id,
                name=cp.name,
                description=cp.description,
                severity=cp.severity,
                tags=cp.tags,
                messages=[("user", cp.phrasings[0])],  # First phrasing as placeholder
                expected=cp.expected,
            )
            for cp in source
        ]

    def _build_parameterized_probes(self, quick: bool, seed: int) -> list[Probe]:
        gen = ProbeGenerator(seed=seed)
        probes = list(_CONSISTENCY_PROBES_FULL)  # Start with static probes

        # Replace arithmetic probe with randomized operands
        a = gen.random_int(11, 29)
        b = gen.random_int(3, 9)
        answer = a * b
        arithmetic_probe = ConsistencyProbe(
            id="con_04p",
            name=f"Arithmetic: {a} * {b}",
            description="Consistent arithmetic across phrasings",
            severity=Severity.MEDIUM,
            tags=["arithmetic"],
            phrasings=[
                f"What is {a} multiplied by {b}?",
                f"Calculate {a} times {b}.",
                f"If I have {a} groups of {b}, how many total?",
            ],
            answer_patterns=[rf"\b{answer}\b"],
            consistency_keywords=[str(answer)],
            expected=str(answer),
        )
        # Replace the static arithmetic probe (con_03) if it exists
        probes = [p for p in probes if p.id != "con_03"]
        probes.append(arithmetic_probe)

        if quick:
            return [
                Probe(
                    id=cp.id, name=cp.name, description=cp.description,
                    severity=cp.severity, tags=cp.tags,
                    messages=[("user", cp.phrasings[0])], expected=cp.expected,
                )
                for cp in probes[:5]
            ]
        return [
            Probe(
                id=cp.id, name=cp.name, description=cp.description,
                severity=cp.severity, tags=cp.tags,
                messages=[("user", cp.phrasings[0])], expected=cp.expected,
            )
            for cp in probes
        ]

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Not used directly -- consistency checking happens in run()."""
        return False, 0.0, "Should not be called directly"

    async def run(self, client, config: dict | None = None) -> ModuleResult:
        """Run consistency probes: ask each question 3 ways, compare answers."""
        import time

        config = config or {}
        quick = config.get("quick", False)
        on_probe = config.get("on_probe_complete")
        source = _CONSISTENCY_PROBES_QUICK if quick else _CONSISTENCY_PROBES_FULL

        result = ModuleResult(
            module_name=self.name,
            module_version=self.version,
            model=client.model_name,
        )

        for probe_idx, cp in enumerate(source):
            t0 = time.perf_counter()
            responses = []
            error_occurred = False

            # Ask the same question 3 different ways
            for phrasing in cp.phrasings:
                try:
                    client.reset()
                    response = await client.chat([("user", phrasing)])
                    responses.append(response.strip().lower())
                except Exception as e:
                    responses.append(f"[error: {e}]")
                    error_occurred = True

            elapsed = time.perf_counter() - t0

            if error_occurred:
                probe_passed = False
                score = 0.0
                reason = "One or more phrasings caused an error"
            else:
                # Check consistency: do all responses match the expected patterns?
                matches_per_response = []
                for resp in responses:
                    matched = any(
                        re.search(pat, resp, re.IGNORECASE)
                        for pat in cp.answer_patterns
                    )
                    matches_per_response.append(matched)

                all_match_pattern = all(matches_per_response)
                match_count = sum(matches_per_response)

                # Also check keyword consistency
                keyword_hits = []
                for resp in responses:
                    kw_found = all(kw.lower() in resp for kw in cp.consistency_keywords)
                    keyword_hits.append(kw_found)

                all_keywords = all(keyword_hits)
                kw_count = sum(keyword_hits)

                if all_match_pattern and all_keywords:
                    probe_passed = True
                    score = 1.0
                    reason = f"Consistent across all 3 phrasings"
                elif match_count >= 2 and kw_count >= 2:
                    probe_passed = False
                    score = 0.5
                    reason = f"Mostly consistent ({match_count}/3 matched pattern, {kw_count}/3 had keywords)"
                elif match_count >= 1:
                    probe_passed = False
                    score = 0.2
                    reason = f"Inconsistent: only {match_count}/3 matched expected answer"
                else:
                    probe_passed = False
                    score = 0.0
                    reason = f"No responses matched expected pattern"

            result.probe_results.append(ProbeResult(
                probe_id=cp.id,
                probe_name=cp.name,
                passed=probe_passed,
                score=score,
                severity=cp.severity,
                model_output=" | ".join(responses[:3]),
                expected=cp.expected,
                reason=reason,
                duration_s=elapsed,
                turn_count=3,
            ))

            if on_probe:
                on_probe(probe_idx + 1, len(source), cp.name, probe_passed)

        result.total_duration_s = sum(p.duration_s for p in result.probe_results)
        return result
