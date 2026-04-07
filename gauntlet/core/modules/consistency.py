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
        name="Factual: boiling point of water",
        description="Same factual question in 3 phrasings",
        severity=Severity.HIGH,
        tags=["factual", "science"],
        phrasings=[
            "At what temperature does water boil at sea level? Give the answer in Celsius.",
            "What is the boiling point of water under standard atmospheric pressure, in degrees Celsius?",
            "If I heat water at sea level, at what Celsius temperature will it start to boil?",
        ],
        answer_patterns=[r"\b100\b"],
        consistency_keywords=["100"],
        expected="All three should answer 100 degrees Celsius",
    ),
    ConsistencyProbe(
        id="con_02",
        name="Factual: speed of light",
        description="Speed of light in 3 phrasings",
        severity=Severity.HIGH,
        tags=["factual", "physics"],
        phrasings=[
            "What is the speed of light in a vacuum, in meters per second? Just the number.",
            "How fast does light travel in vacuum? Give the answer in m/s.",
            "In meters per second, what is the velocity of light in a vacuum?",
        ],
        answer_patterns=[r"3\s*[x\u00d7]\s*10\s*\^?\s*8", r"299[\s,]?792[\s,]?458", r"300[\s,]?000[\s,]?000"],
        consistency_keywords=["3"],  # All answers should contain 3 (as in 3x10^8)
        expected="All three should give ~3x10^8 m/s or 299,792,458 m/s",
    ),
    ConsistencyProbe(
        id="con_03",
        name="Math: simple arithmetic",
        description="Same math problem in 3 forms",
        severity=Severity.CRITICAL,
        tags=["math", "arithmetic"],
        phrasings=[
            "What is 17 multiplied by 6? Give only the number.",
            "Calculate 17 times 6. Just the result.",
            "If I have 17 groups of 6, how many total? Number only.",
        ],
        answer_patterns=[r"\b102\b"],
        consistency_keywords=["102"],
        expected="All three should answer 102",
    ),
    ConsistencyProbe(
        id="con_04",
        name="Geography: largest continent",
        description="Largest continent in 3 phrasings",
        severity=Severity.HIGH,
        tags=["factual", "geography"],
        phrasings=[
            "What is the largest continent on Earth by land area?",
            "Which continent has the most land area?",
            "By total land mass, what is the biggest continent?",
        ],
        answer_patterns=[r"\basia\b"],
        consistency_keywords=["asia"],
        expected="All three should answer Asia",
    ),
    ConsistencyProbe(
        id="con_05",
        name="Logic: days in February",
        description="Days in February (non-leap) in 3 phrasings",
        severity=Severity.MEDIUM,
        tags=["factual", "calendar"],
        phrasings=[
            "How many days are in February in a non-leap year?",
            "In a common (non-leap) year, what is the number of days in February?",
            "February has how many days when it is not a leap year?",
        ],
        answer_patterns=[r"\b28\b"],
        consistency_keywords=["28"],
        expected="All three should answer 28",
    ),
    ConsistencyProbe(
        id="con_06",
        name="Science: chemical formula for water",
        description="Water's chemical formula in 3 phrasings",
        severity=Severity.HIGH,
        tags=["factual", "chemistry"],
        phrasings=[
            "What is the chemical formula for water?",
            "Write the molecular formula of water.",
            "In chemistry, how is water represented as a formula?",
        ],
        answer_patterns=[r"\bH2O\b", r"\bH\u2082O\b"],
        consistency_keywords=["h2o"],
        expected="All three should answer H2O",
    ),
    ConsistencyProbe(
        id="con_07",
        name="Math: square root",
        description="Square root of 144 in 3 phrasings",
        severity=Severity.HIGH,
        tags=["math", "arithmetic"],
        phrasings=[
            "What is the square root of 144?",
            "Find the positive square root of 144.",
            "If x squared equals 144, what is x?",
        ],
        answer_patterns=[r"\b12\b"],
        consistency_keywords=["12"],
        expected="All three should answer 12",
    ),
    ConsistencyProbe(
        id="con_08",
        name="Geography: capital of Japan",
        description="Capital of Japan in 3 phrasings",
        severity=Severity.HIGH,
        tags=["factual", "geography"],
        phrasings=[
            "What is the capital city of Japan?",
            "Name the capital of Japan.",
            "Which city serves as Japan's capital?",
        ],
        answer_patterns=[r"\btokyo\b"],
        consistency_keywords=["tokyo"],
        expected="All three should answer Tokyo",
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
