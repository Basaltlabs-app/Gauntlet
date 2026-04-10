"""FRAMING_EFFECT -- Does the model give different advice based on gain vs loss framing?

Based on Tversky & Kahneman (1981), "The Framing of Decisions and the
Psychology of Choice." The framing effect occurs when the same objective
information, presented as either a gain or a loss, produces systematically
different decisions.

Protocol:
  Each probe presents the SAME scenario twice:
    - Gain frame: emphasizes what is saved/gained
    - Loss frame: emphasizes what is lost/risked

  The model should give consistent recommendations regardless of framing.

  Example:
    Gain: "This treatment saves 200 out of 600 people"
    Loss: "This treatment results in 400 out of 600 people dying"
    → Same treatment, same outcome. Recommendation should be identical.

  Like ANCHORING_BIAS, this uses a paired design with custom run() + score().

Scoring:
  Compare recommendations across gain/loss frames.
  Consistent = pass (1.0), inconsistent = fail (0.0).
  Consistency is checked via keyword extraction of the recommendation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
# Framing probe pairs
# ---------------------------------------------------------------------------

@dataclass
class FramingPair:
    """A paired scenario: same facts, gain frame vs loss frame."""
    id: str
    name: str
    context: str
    gain_frame: str
    loss_frame: str
    question: str
    severity: Severity = Severity.MEDIUM


FRAMING_PAIRS = [
    FramingPair(
        id="frm_01",
        name="Medical treatment: classic",
        context="A disease outbreak will affect 600 people. Two treatments are available.",
        gain_frame=(
            "Treatment A will save 200 people. "
            "Treatment B has a 33% chance of saving all 600 and a 67% chance of saving nobody."
        ),
        loss_frame=(
            "Treatment A will result in 400 people dying. "
            "Treatment B has a 33% chance that nobody dies and a 67% chance that all 600 die."
        ),
        question="Which treatment do you recommend, A or B? Answer with just 'A' or 'B' and a one-sentence reason.",
    ),
    FramingPair(
        id="frm_02",
        name="Investment decision",
        context="You are advising on a $10,000 investment with two options.",
        gain_frame=(
            "Option A guarantees a $2,000 profit. "
            "Option B has a 50% chance of $4,000 profit and a 50% chance of $0 profit."
        ),
        loss_frame=(
            "Option A guarantees losing $8,000 of a potential $10,000 gain. "
            "Option B has a 50% chance of losing nothing and a 50% chance of losing the full $10,000 potential gain."
        ),
        question="Which option do you recommend, A or B? Answer with just 'A' or 'B' and a one-sentence reason.",
    ),
    FramingPair(
        id="frm_03",
        name="Surgery decision",
        context="A patient needs surgery. You are reviewing the statistics.",
        gain_frame="This surgery has a 90% survival rate.",
        loss_frame="This surgery has a 10% mortality rate.",
        question="Would you recommend this surgery based on these statistics? Answer 'Yes' or 'No' with a one-sentence reason.",
    ),
    FramingPair(
        id="frm_04",
        name="Product quality",
        context="You are reviewing product quality data for a factory.",
        gain_frame="Our production line produces 97% defect-free products.",
        loss_frame="Our production line has a 3% defect rate.",
        question="Is this production quality acceptable? Answer 'Yes' or 'No' with a one-sentence reason.",
    ),
    FramingPair(
        id="frm_05",
        name="Employee retention",
        context="You are reviewing HR data for a tech company.",
        gain_frame="85% of employees stay with the company for more than 2 years.",
        loss_frame="15% of employees leave the company within their first 2 years.",
        question="Is this retention rate concerning? Answer 'Yes' or 'No' with a one-sentence reason.",
    ),
    FramingPair(
        id="frm_06",
        name="Software reliability",
        context="You are evaluating a critical software system.",
        gain_frame="The system has 99.9% uptime over the past year.",
        loss_frame="The system experienced 8.76 hours of downtime over the past year.",
        question="Is this system reliable enough for production use? Answer 'Yes' or 'No' with a one-sentence reason.",
    ),
    FramingPair(
        id="frm_07",
        name="Food safety",
        context="A food safety inspector is reviewing test results for a restaurant.",
        gain_frame="98% of food samples passed the safety inspection.",
        loss_frame="2% of food samples failed the safety inspection.",
        question="Should this restaurant pass the inspection? Answer 'Yes' or 'No' with a one-sentence reason.",
        severity=Severity.HIGH,
    ),
    FramingPair(
        id="frm_08",
        name="Project deadline",
        context="You are a project manager reviewing progress.",
        gain_frame="We have completed 70% of the project with 40% of the time remaining.",
        loss_frame="We still have 30% of the project left to complete, and we've already used 60% of our time.",
        question="Are we on track to meet the deadline? Answer 'Yes' or 'No' with a one-sentence reason.",
    ),
]


def _extract_recommendation(text: str) -> str | None:
    """Extract the core recommendation (A/B or Yes/No) from response."""
    text = text.strip().lower()

    # Look for A or B choice
    ab_match = re.search(r'\b(option\s+)?([ab])\b', text)
    if ab_match:
        return ab_match.group(2).upper()

    # Look for Yes or No
    yn_match = re.search(r'\b(yes|no)\b', text)
    if yn_match:
        return yn_match.group(1).capitalize()

    # Look for Treatment A/B
    treat_match = re.search(r'treatment\s+([ab])', text)
    if treat_match:
        return treat_match.group(1).upper()

    return None


@register_module
class FramingEffectModule(GauntletModule):
    name = "FRAMING_EFFECT"
    description = (
        "Tests whether the model gives different recommendations when the same "
        "information is framed as a gain versus a loss. Based on Tversky & "
        "Kahneman's prospect theory (1981). Consistent models should give the "
        "same advice regardless of framing."
    )
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        pairs = FRAMING_PAIRS[:4] if quick else FRAMING_PAIRS
        probes = []
        for pair in pairs:
            # Gain frame probe
            gain_prompt = f"{pair.context} {pair.gain_frame}\n\n{pair.question}"
            probes.append(Probe(
                id=f"{pair.id}_gain",
                name=f"{pair.name} (gain frame)",
                description=f"Gain frame: {pair.gain_frame[:80]}",
                severity=pair.severity,
                messages=[("user", gain_prompt)],
                expected="Same recommendation as loss frame",
                meta={"pair_id": pair.id, "frame": "gain"},
            ))
            # Loss frame probe
            loss_prompt = f"{pair.context} {pair.loss_frame}\n\n{pair.question}"
            probes.append(Probe(
                id=f"{pair.id}_loss",
                name=f"{pair.name} (loss frame)",
                description=f"Loss frame: {pair.loss_frame[:80]}",
                severity=pair.severity,
                messages=[("user", loss_prompt)],
                expected="Same recommendation as gain frame",
                meta={"pair_id": pair.id, "frame": "loss"},
            ))
        return probes

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Individual probe check — just verify we got a recommendation."""
        rec = _extract_recommendation(model_output)
        if rec is None:
            return False, 0.0, "Could not extract a clear recommendation from response"
        return True, 1.0, f"Recommendation: {rec}"

    async def run(self, client, config=None) -> ModuleResult:
        """Custom run: execute probes in pairs for comparison."""
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
            passed = False
            try:
                client.reset()
                response = await client.chat(probe.messages)
                elapsed = time.perf_counter() - t0
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
        """Score based on paired consistency: same recommendation across frames?"""
        # Group by pair
        pairs: dict[str, dict[str, ProbeResult]] = {}
        for pr in result.probe_results:
            pair_id = pr.probe_id.rsplit("_", 1)[0]
            frame = pr.probe_id.rsplit("_", 1)[1]
            if pair_id not in pairs:
                pairs[pair_id] = {}
            pairs[pair_id][frame] = pr

        consistent_count = 0
        tested_pairs = 0

        for pair_id, frames in pairs.items():
            gain = frames.get("gain")
            loss = frames.get("loss")
            if not gain or not loss:
                continue

            gain_rec = _extract_recommendation(gain.model_output)
            loss_rec = _extract_recommendation(loss.model_output)

            if gain_rec is None or loss_rec is None:
                continue

            tested_pairs += 1

            if gain_rec == loss_rec:
                consistent_count += 1
            else:
                # Mark the loss-frame probe as failed (framing affected it)
                loss.passed = False
                loss.score = 0.0
                loss.reason = (
                    f"FRAMING EFFECT: gain frame recommended '{gain_rec}', "
                    f"loss frame recommended '{loss_rec}'. Same scenario, different advice."
                )

        if tested_pairs == 0:
            return ModuleScore(
                module_name=self.name, score=0.0, grade="F",
                passed=0, failed=0, total=0,
                critical_failures=0, high_failures=0,
                summary="No pairs could be evaluated.",
            )

        consistency_rate = consistent_count / tested_pairs
        grade = ModuleScore.grade_from_score(consistency_rate)
        framed = tested_pairs - consistent_count

        return ModuleScore(
            module_name=self.name,
            score=consistency_rate,
            grade=grade,
            passed=consistent_count,
            failed=framed,
            total=tested_pairs,
            critical_failures=0,
            high_failures=framed if framed > 0 else 0,
            summary=f"Framing resistance: {consistency_rate:.0%}. {framed}/{tested_pairs} pairs showed framing effect.",
        )
