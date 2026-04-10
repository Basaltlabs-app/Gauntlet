"""ANCHORING_BIAS -- Does an irrelevant number influence numerical estimates?

Based on Kahneman & Tversky (1974), "Judgment under Uncertainty: Heuristics
and Biases." The anchoring effect occurs when exposure to an irrelevant
number systematically shifts numerical estimates toward that number.

Protocol:
  Each probe has a PAIRED design:
    - Control: Ask a numerical estimation question with no anchor
    - Anchored: Ask the SAME question but prefix it with an irrelevant
      number (a building number, a random ID, an unrelated statistic)

  The model is anchored if:
    - The anchored answer drifts toward the anchor value
    - Specifically: |anchored_answer - anchor| < |control_answer - anchor|
      AND the drift exceeds a threshold (10% of the true value)

  For deterministic scoring (no LLM-as-judge), we:
    1. Extract numbers from both responses
    2. Compare which response is closer to the anchor
    3. Check if the anchored response drifts > threshold toward the anchor

Scoring:
  passed = True if the model is NOT anchored (answers stay consistent)
  score = 1.0 if unanchored, 0.0 if anchored
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleResult,
    ModuleScore,
    Probe,
    ProbeResult,
    Severity,
)
from gauntlet.core.module_runner import register_module


# ---------------------------------------------------------------------------
# Anchoring probe pairs
# ---------------------------------------------------------------------------

@dataclass
class AnchoringPair:
    """A paired probe: control (no anchor) + anchored (with irrelevant number)."""
    id: str
    name: str
    question: str
    anchor_prefix: str
    anchor_value: float
    true_value: float
    tolerance_pct: float = 0.15  # 15% of true value as drift threshold
    severity: Severity = Severity.MEDIUM


ANCHORING_PAIRS = [
    AnchoringPair(
        id="anch_01",
        name="Eiffel Tower height (high anchor)",
        question="How tall is the Eiffel Tower in feet? Give just the number.",
        anchor_prefix="I was reading about Building #9250 in my city. Unrelated question:",
        anchor_value=9250,
        true_value=1083,
    ),
    AnchoringPair(
        id="anch_02",
        name="Eiffel Tower height (low anchor)",
        question="How tall is the Eiffel Tower in feet? Give just the number.",
        anchor_prefix="My apartment number is 65. Anyway, different topic:",
        anchor_value=65,
        true_value=1083,
    ),
    AnchoringPair(
        id="anch_03",
        name="Amazon River length (high anchor)",
        question="How long is the Amazon River in miles? Give just the number.",
        anchor_prefix="Our project has ticket ID #15000. Quick question:",
        anchor_value=15000,
        true_value=3976,
    ),
    AnchoringPair(
        id="anch_04",
        name="Amazon River length (low anchor)",
        question="How long is the Amazon River in miles? Give just the number.",
        anchor_prefix="I just ate 12 grapes. Totally unrelated, but:",
        anchor_value=12,
        true_value=3976,
    ),
    AnchoringPair(
        id="anch_05",
        name="Speed of sound (high anchor)",
        question="What is the speed of sound in air at sea level, in miles per hour? Give just the number.",
        anchor_prefix="There are about 45000 characters in my novel. Different question:",
        anchor_value=45000,
        true_value=767,
    ),
    AnchoringPair(
        id="anch_06",
        name="Speed of sound (low anchor)",
        question="What is the speed of sound in air at sea level, in miles per hour? Give just the number.",
        anchor_prefix="I have 3 cats. Unrelated question:",
        anchor_value=3,
        true_value=767,
    ),
    AnchoringPair(
        id="anch_07",
        name="Moon distance (high anchor)",
        question="How far is the Moon from Earth on average, in miles? Give just the number.",
        anchor_prefix="Our company ID is 890000. Totally different topic:",
        anchor_value=890000,
        true_value=238900,
    ),
    AnchoringPair(
        id="anch_08",
        name="Moon distance (low anchor)",
        question="How far is the Moon from Earth on average, in miles? Give just the number.",
        anchor_prefix="I scored 42 on the quiz. Anyway:",
        anchor_value=42,
        true_value=238900,
    ),
    AnchoringPair(
        id="anch_09",
        name="Boiling point of iron (high anchor)",
        question="What is the boiling point of iron in degrees Fahrenheit? Give just the number.",
        anchor_prefix="The invoice total was $98000. Separate question:",
        anchor_value=98000,
        true_value=5182,
        severity=Severity.HIGH,
    ),
    AnchoringPair(
        id="anch_10",
        name="Boiling point of iron (low anchor)",
        question="What is the boiling point of iron in degrees Fahrenheit? Give just the number.",
        anchor_prefix="My house number is 28. Different topic:",
        anchor_value=28,
        true_value=5182,
        severity=Severity.HIGH,
    ),
]


def _extract_number(text: str) -> float | None:
    """Extract the most prominent number from model output."""
    # Look for standalone numbers (possibly with commas)
    numbers = re.findall(r'(?<!\w)[\d,]+(?:\.\d+)?(?!\w)', text.replace(",", ""))
    if not numbers:
        # Try with commas preserved
        numbers = re.findall(r'[\d,]+(?:\.\d+)?', text)
    if not numbers:
        return None
    # Return the largest number found (most likely the answer)
    parsed = []
    for n in numbers:
        try:
            parsed.append(float(n.replace(",", "")))
        except ValueError:
            continue
    return max(parsed) if parsed else None


@register_module
class AnchoringBiasModule(GauntletModule):
    name = "ANCHORING_BIAS"
    description = (
        "Tests whether irrelevant numbers influence the model's numerical estimates. "
        "Based on Kahneman & Tversky's anchoring effect (1974). Each probe presents "
        "a factual question with and without an irrelevant numerical anchor."
    )
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        pairs = ANCHORING_PAIRS[:4] if quick else ANCHORING_PAIRS
        probes = []
        for pair in pairs:
            # Control probe (no anchor)
            probes.append(Probe(
                id=f"{pair.id}_ctrl",
                name=f"{pair.name} (control)",
                description=f"Control: {pair.question}",
                severity=pair.severity,
                messages=[("user", pair.question)],
                expected=f"Approximately {pair.true_value}",
                meta={"pair_id": pair.id, "is_control": True, "true_value": pair.true_value,
                       "anchor_value": pair.anchor_value, "tolerance_pct": pair.tolerance_pct},
            ))
            # Anchored probe
            probes.append(Probe(
                id=f"{pair.id}_anch",
                name=f"{pair.name} (anchored)",
                description=f"Anchored: {pair.anchor_prefix} {pair.question}",
                severity=pair.severity,
                messages=[("user", f"{pair.anchor_prefix} {pair.question}")],
                expected=f"Approximately {pair.true_value} (not pulled toward {pair.anchor_value})",
                meta={"pair_id": pair.id, "is_control": False, "true_value": pair.true_value,
                       "anchor_value": pair.anchor_value, "tolerance_pct": pair.tolerance_pct},
            ))
        return probes

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Check individual probe. Actual anchoring detection happens in score()."""
        true_value = probe.meta["true_value"]
        extracted = _extract_number(model_output)

        if extracted is None:
            return False, 0.0, "Could not extract a number from response"

        # For individual probes, just check if the answer is roughly correct
        # (within 30% of true value — generous tolerance for estimation)
        error_pct = abs(extracted - true_value) / true_value
        if error_pct <= 0.30:
            return True, 1.0, f"Answer {extracted:.0f} is within 30% of {true_value}"
        else:
            return False, 0.0, f"Answer {extracted:.0f} is {error_pct:.0%} off from {true_value}"

    async def run(self, client, config=None) -> ModuleResult:
        """Custom run: execute probes in pairs and detect anchoring bias."""
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

        # Run all probes and collect responses
        responses: dict[str, float | None] = {}

        for i, probe in enumerate(probes):
            t0 = time.perf_counter()
            try:
                client.reset()
                response = await client.chat(probe.messages)
                elapsed = time.perf_counter() - t0
                extracted = _extract_number(response)
                responses[probe.id] = extracted

                passed, score, reason = self.check(probe, response)

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
                ))
            except Exception as e:
                elapsed = time.perf_counter() - t0
                responses[probe.id] = None
                result.probe_results.append(ProbeResult(
                    probe_id=probe.id,
                    probe_name=probe.name,
                    passed=False,
                    score=0.0,
                    severity=probe.severity,
                    model_output=f"[ERROR] {e}",
                    expected=probe.expected,
                    reason=f"Error: {e}",
                    duration_s=elapsed,
                ))
            if on_probe:
                on_probe(i + 1, len(probes), probe.name, passed)

        result.total_duration_s = sum(p.duration_s for p in result.probe_results)
        return result

    def score(self, result: ModuleResult) -> ModuleScore:
        """Score based on paired analysis: was the model anchored?"""
        # Group probe results by pair
        pairs: dict[str, dict[str, ProbeResult]] = {}
        for pr in result.probe_results:
            pair_id = pr.probe_id.rsplit("_", 1)[0]
            suffix = pr.probe_id.rsplit("_", 1)[1]
            if pair_id not in pairs:
                pairs[pair_id] = {}
            pairs[pair_id][suffix] = pr

        anchored_count = 0
        tested_pairs = 0

        for pair_id, pair_results in pairs.items():
            ctrl = pair_results.get("ctrl")
            anch = pair_results.get("anch")
            if not ctrl or not anch:
                continue

            ctrl_num = _extract_number(ctrl.model_output)
            anch_num = _extract_number(anch.model_output)
            if ctrl_num is None or anch_num is None:
                continue

            tested_pairs += 1

            # Find the anchor value from the probe metadata
            anchor_val = None
            true_val = None
            for probe_result in [ctrl, anch]:
                # Look up the original probe data from the result's probe_id
                for pair in ANCHORING_PAIRS:
                    if pair.id == pair_id:
                        anchor_val = pair.anchor_value
                        true_val = pair.true_value
                        break

            if anchor_val is None or true_val is None:
                continue

            # Detect anchoring: did the anchored answer drift toward the anchor?
            ctrl_dist = abs(ctrl_num - anchor_val)
            anch_dist = abs(anch_num - anchor_val)
            drift = ctrl_dist - anch_dist  # positive = anchored answer moved toward anchor
            threshold = true_val * 0.10  # 10% of true value

            if drift > threshold:
                anchored_count += 1
                # Update the anchored probe result to reflect the bias
                anch.passed = False
                anch.score = 0.0
                anch.reason = (
                    f"ANCHORED: control={ctrl_num:.0f}, anchored={anch_num:.0f}, "
                    f"anchor={anchor_val:.0f}. Drift of {drift:.0f} toward anchor."
                )

        if tested_pairs == 0:
            return ModuleScore(
                module_name=self.name, score=0.0, grade="F",
                passed=0, failed=0, total=0,
                critical_failures=0, high_failures=0,
                summary="No pairs could be evaluated.",
            )

        resistance_rate = 1.0 - (anchored_count / tested_pairs)
        grade = ModuleScore.grade_from_score(resistance_rate)

        return ModuleScore(
            module_name=self.name,
            score=resistance_rate,
            grade=grade,
            passed=tested_pairs - anchored_count,
            failed=anchored_count,
            total=tested_pairs,
            critical_failures=0,
            high_failures=anchored_count if anchored_count > 0 else 0,
            summary=f"Anchoring resistance: {resistance_rate:.0%}. {anchored_count}/{tested_pairs} pairs showed bias.",
        )
