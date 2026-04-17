"""Report generation -- Finding dataclass, module labels, and template verdicts.

Finding is the canonical data structure for behavioral observations.
It is imported by trust_score.py and display modules.
Verdicts are template-based (not LLM-generated).
"""

from __future__ import annotations
from dataclasses import dataclass


# ── MODULE_LABELS ──────────────────────────────────────────────────────
# Human-readable names for each module. Used by CLI, TUI, HTML reports,
# and dashboard displays.
#
# ARCHITECTURE NOTE (V2): This dict is the OVERRIDE layer. Any module
# not listed here gets an auto-generated label from its class `name`
# attribute (e.g. "LAYER_SENSITIVITY" → "Layer Sensitivity"). So you
# only need an entry here when the auto-generated label isn't good enough
# (e.g. "SYCOPHANCY_TRAP" → "Sycophancy Resistance" is better than the
# auto-generated "Sycophancy Trap").
#
# To add a new module: just create the module file with @register_module.
# It will auto-appear in all interfaces. Only add an override here if
# the auto-label reads poorly.

_MODULE_LABEL_OVERRIDES: dict[str, str] = {
    "SYCOPHANCY_TRAP": "Sycophancy Resistance",
    "INSTRUCTION_ADHERENCE": "Instruction Following",
    "CONSISTENCY_DRIFT": "Consistency",
    "HALLUCINATION_PROBE": "Hallucination Resistance",
    "CONTEXT_FIDELITY": "Context Recall",
    "PROMPT_INJECTION": "Injection Resistance",
}


def _auto_label(module_name: str) -> str:
    """Convert 'LAYER_SENSITIVITY' → 'Layer Sensitivity' automatically."""
    return module_name.replace("_", " ").title()


def _build_module_labels() -> dict[str, str]:
    """Build the full label dict: overrides + auto-generated for the rest.

    Lazily imports the module registry so this doesn't create circular
    imports (report.py is imported by modules themselves).
    """
    labels = dict(_MODULE_LABEL_OVERRIDES)
    try:
        from gauntlet.core.module_runner import load_all_modules, list_modules
        load_all_modules()
        for mod in list_modules():
            if mod.name not in labels:
                labels[mod.name] = _auto_label(mod.name)
    except Exception:
        # Fallback: if module loading fails, at least return the overrides.
        # This can happen during early import before all deps are available.
        pass
    return labels


# Lazy singleton: built on first access, then cached.
_cached_labels: dict[str, str] | None = None


def get_module_labels() -> dict[str, str]:
    """Get the full MODULE_LABELS dict. Auto-discovers all registered modules."""
    global _cached_labels
    if _cached_labels is None:
        _cached_labels = _build_module_labels()
    return _cached_labels


# Backwards-compatible alias: existing code imports MODULE_LABELS directly.
# We can't make it a lazy property on a module (Python doesn't support that
# cleanly), so we populate it eagerly with the overrides and add a note that
# get_module_labels() is the preferred access path.
MODULE_LABELS: dict[str, str] = dict(_MODULE_LABEL_OVERRIDES)


def refresh_module_labels() -> None:
    """Re-scan the registry and update MODULE_LABELS in place.

    Call this after load_all_modules() if you need the global dict to
    reflect all discovered modules. The CLI/TUI call this at startup.
    """
    global _cached_labels
    _cached_labels = _build_module_labels()
    MODULE_LABELS.clear()
    MODULE_LABELS.update(_cached_labels)

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
