"""Report generation -- Finding dataclass, module labels, and template verdicts.

Finding is the canonical data structure for behavioral observations.
It is imported by trust_score.py and display modules.
Verdicts are template-based (not LLM-generated).
"""

from __future__ import annotations
from dataclasses import dataclass


MODULE_LABELS: dict[str, str] = {
    "AMBIGUITY_HONESTY": "Ambiguity Honesty",
    "SYCOPHANCY_TRAP": "Sycophancy Resistance",
    "INSTRUCTION_ADHERENCE": "Instruction Following",
    "CONSISTENCY_DRIFT": "Consistency",
    "SAFETY_BOUNDARY": "Safety",
    "HALLUCINATION_PROBE": "Hallucination Resistance",
    "CONTEXT_FIDELITY": "Context Recall",
    "REFUSAL_CALIBRATION": "Refusal Calibration",
    "SYCOPHANCY_GRADIENT": "Sycophancy Gradient",
    "INSTRUCTION_DECAY": "Instruction Decay",
    "TEMPORAL_COHERENCE": "Temporal Coherence",
    "CONFIDENCE_CALIBRATION": "Confidence Calibration",
    "ANCHORING_BIAS": "Anchoring Bias",
    "PROMPT_INJECTION": "Injection Resistance",
    "LOGICAL_CONSISTENCY": "Logical Consistency",
    "FRAMING_EFFECT": "Framing Effect",
    "CONTAMINATION_CHECK": "Contamination Check",
}

_PROFILE_LABELS: dict[str, str] = {
    "assistant": "assistant tasks",
    "coder": "coding tasks",
    "researcher": "research tasks",
    "raw": "general use",
}


@dataclass
class Finding:
    """A plain-English behavioral finding from a probe result."""
    level: str                        # "CRITICAL", "WARNING", "CLEAN"
    summary: str
    module_name: str
    probe_id: str | None = None
    probe_name: str | None = None
    deduction: float = 0.0

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "summary": self.summary,
            "module_name": self.module_name,
            "probe_id": self.probe_id,
            "probe_name": self.probe_name,
            "deduction": round(self.deduction, 2),
        }


def generate_verdict(
    model_scores: list[tuple[str, "TrustScore"]],
    profile: str = "raw",
) -> str | None:
    if len(model_scores) < 2:
        return None

    ranked = sorted(model_scores, key=lambda x: x[1].score, reverse=True)
    winner_name, winner_ts = ranked[0]
    runner_name, runner_ts = ranked[1]
    profile_label = _PROFILE_LABELS.get(profile, "general use")

    if winner_ts.score == runner_ts.score:
        winner_strengths = _get_exclusive_clean(winner_ts, runner_ts)
        runner_strengths = _get_exclusive_clean(runner_ts, winner_ts)
        if not winner_strengths and not runner_strengths:
            return f"Both models scored {winner_ts.score}/100. They performed identically across all dimensions."
        parts = [f"Both models scored {winner_ts.score}/100."]
        if winner_strengths:
            labels = [MODULE_LABELS.get(m, m) for m in winner_strengths[:3]]
            parts.append(f"{winner_name} is stronger at {', '.join(labels)}.")
        if runner_strengths:
            labels = [MODULE_LABELS.get(m, m) for m in runner_strengths[:3]]
            parts.append(f"{runner_name} is stronger at {', '.join(labels)}.")
        return " ".join(parts)

    parts = [f"{winner_name} is more reliable for {profile_label} ({winner_ts.score}/100 vs {runner_ts.score}/100)."]
    winner_strengths = _get_exclusive_clean(winner_ts, runner_ts)
    runner_strengths = _get_exclusive_clean(runner_ts, winner_ts)
    if winner_strengths:
        labels = [MODULE_LABELS.get(m, m) for m in winner_strengths[:3]]
        parts.append(f"Led in {', '.join(labels)}.")
    if runner_strengths:
        labels = [MODULE_LABELS.get(m, m) for m in runner_strengths[:3]]
        parts.append(f"{runner_name} was stronger at {', '.join(labels)}.")
    if winner_ts.has_critical_safety:
        parts.append(f"Warning: {winner_name} had critical safety failures.")
    if runner_ts.has_critical_safety:
        parts.append(f"Warning: {runner_name} had critical safety failures.")
    return " ".join(parts)


def _get_exclusive_clean(model_a: "TrustScore", model_b: "TrustScore") -> list[str]:
    a_clean = set(model_a.clean_modules)
    b_clean = set(model_b.clean_modules)
    return sorted(a_clean - b_clean)
