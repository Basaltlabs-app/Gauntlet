"""Recommendation engine -- generates actionable advice from comparison results.

Deterministic template engine. No LLM calls. Reads scored ComparisonResult
and produces human-friendly text explaining why the winner won in terms
that matter for the user's specific task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gauntlet.core.metrics import ComparisonResult


# Subcategory → human-readable task label
_TASK_LABELS: dict[str, str] = {
    "database": "database",
    "auth_security": "auth & security",
    "apps_script": "Google Apps Script",
    "frontend": "frontend",
    "backend_api": "backend API",
    "devops": "DevOps",
    "data_analysis": "data analysis",
    "writing_content": "writing",
}


def generate_recommendation(result: "ComparisonResult") -> Optional[str]:
    """Generate an actionable recommendation from a scored comparison.

    Returns a human-readable paragraph explaining:
    1. Who won and for what kind of task
    2. Winner's top strengths (high-scoring dimensions)
    3. Loser's specific issues (concrete problems found)
    4. Speed comparison as context

    Returns None if there's not enough data to make a recommendation.
    """
    if not result.scoring or not result.scoring.winner:
        return None

    valid = [m for m in result.models if not m.output.startswith("[ERROR]")]
    if len(valid) < 2:
        return None

    winner_model = result.scoring.winner
    winner = next((m for m in valid if m.model == winner_model), None)
    losers = [m for m in valid if m.model != winner_model]

    if not winner or not losers:
        return None

    has_classification = (
        result.classification is not None
        and result.classification.subcategory is not None
    )

    parts: list[str] = []

    # 1. Opening: winner + task type
    if has_classification:
        task_label = _TASK_LABELS.get(
            result.classification.subcategory,
            result.classification.subcategory_label or result.classification.subcategory,
        )
        parts.append(f"{winner.model} won for this {task_label} task.")
    else:
        parts.append(f"{winner.model} produced the best overall result.")

    # 2. Winner strengths (dimensions scored >= 7)
    if winner.quality_scores:
        strengths = [
            (name, score)
            for name, score in winner.quality_scores.items()
            if isinstance(score, (int, float)) and score >= 7
        ]
        strengths.sort(key=lambda x: x[1], reverse=True)

        if strengths:
            top = strengths[:3]
            strength_parts = [f"{name}: {score:.0f}/10" for name, score in top]
            parts.append(f"Scored well on {', '.join(strength_parts)}.")

    # 3. Winner had no specific issues
    if has_classification and not winner.specific_issues:
        parts.append("No domain-specific issues detected.")

    # 4. Loser weaknesses + specific issues
    for loser in losers[:2]:  # Cap at 2 losers for readability
        loser_parts: list[str] = []

        # Specific issues (most valuable signal)
        if loser.specific_issues:
            issues = loser.specific_issues[:3]
            issues_text = "; ".join(issues)
            loser_parts.append(issues_text)

        # Low-scoring dimensions
        if loser.quality_scores:
            weak = [
                (name, score)
                for name, score in loser.quality_scores.items()
                if isinstance(score, (int, float)) and score <= 5
            ]
            weak.sort(key=lambda x: x[1])
            if weak:
                weak_top = weak[:2]
                weak_text = ", ".join(
                    f"{name}: {score:.0f}/10" for name, score in weak_top
                )
                loser_parts.append(weak_text)

        if loser_parts:
            parts.append(f"{loser.model}: {'. '.join(loser_parts)}.")

    # 5. Speed comparison
    speed_note = _speed_comparison(winner, losers)
    if speed_note:
        parts.append(speed_note)

    return " ".join(parts)


def _speed_comparison(winner, losers) -> Optional[str]:
    """Generate a speed comparison note."""
    winner_tps = winner.tokens_per_sec
    if not winner_tps or winner_tps <= 0:
        return None

    # Compare against the fastest loser
    fastest_loser = max(
        (l for l in losers if l.tokens_per_sec and l.tokens_per_sec > 0),
        key=lambda l: l.tokens_per_sec,
        default=None,
    )
    if not fastest_loser:
        return None

    loser_tps = fastest_loser.tokens_per_sec
    ratio = winner_tps / loser_tps

    if ratio >= 1.1:
        return (
            f"On your hardware, {winner.model} also ran {ratio:.1f}x faster "
            f"({winner_tps:.1f} vs {loser_tps:.1f} tok/s)."
        )
    elif ratio <= 0.9:
        inverse = loser_tps / winner_tps
        return (
            f"{fastest_loser.model} was {inverse:.1f}x faster "
            f"({loser_tps:.1f} vs {winner_tps:.1f} tok/s), "
            f"but the quality gap outweighed the speed difference."
        )
    else:
        return f"Both models ran at similar speeds (~{winner_tps:.0f} tok/s)."
