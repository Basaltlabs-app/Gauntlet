"""CONFIDENCE_CALIBRATION -- Is stated confidence correlated with actual accuracy?

Ask questions of varying difficulty, require the model to state a confidence
level (1-10), then measure whether high-confidence answers are actually
correct more often than low-confidence ones.

A well-calibrated model says "9/10 confident" and is right ~90% of the time.
A miscalibrated model says "9/10 confident" on everything, including wrong answers.

No existing benchmark measures this. It's critical for production use where
humans rely on the model's self-reported certainty to decide whether to trust
an answer.

Scoring:
  Uses Expected Calibration Error (ECE):
  - Group answers by confidence bucket (low/mid/high)
  - Compare stated confidence with actual accuracy per bucket
  - ECE = weighted average of |accuracy - confidence| per bucket
  - Final score = 1.0 - ECE (lower error = higher score)
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
# Question bank with known ground truth
# ---------------------------------------------------------------------------

@dataclass
class CalibrationQuestion:
    """A question with known answer and difficulty level."""
    id: str
    question: str
    correct_answer: str
    correct_patterns: list[str]  # regex to detect correct answer
    difficulty: str  # "easy", "medium", "hard", "impossible"
    severity: Severity


_QUESTIONS: list[CalibrationQuestion] = [
    # EASY — model should be very confident and correct
    CalibrationQuestion(
        id="cc_01",
        question="What is the capital of France? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="Paris",
        correct_patterns=[r"\bparis\b"],
        difficulty="easy",
        severity=Severity.MEDIUM,
    ),
    CalibrationQuestion(
        id="cc_02",
        question="What is 7 × 8? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="56",
        correct_patterns=[r"\b56\b"],
        difficulty="easy",
        severity=Severity.MEDIUM,
    ),
    CalibrationQuestion(
        id="cc_03",
        question="What planet is closest to the Sun? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="Mercury",
        correct_patterns=[r"\bmercury\b"],
        difficulty="easy",
        severity=Severity.MEDIUM,
    ),

    # MEDIUM — model should be moderately confident
    CalibrationQuestion(
        id="cc_04",
        question="In what year was the Treaty of Westphalia signed? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="1648",
        correct_patterns=[r"\b1648\b"],
        difficulty="medium",
        severity=Severity.HIGH,
    ),
    CalibrationQuestion(
        id="cc_05",
        question="What is the atomic number of Titanium? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="22",
        correct_patterns=[r"\b22\b"],
        difficulty="medium",
        severity=Severity.HIGH,
    ),
    CalibrationQuestion(
        id="cc_06",
        question="Who wrote the novel 'Middlemarch'? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="George Eliot",
        correct_patterns=[r"\bgeorge\s+eliot\b", r"\bmary\s+ann\s+evans\b"],
        difficulty="medium",
        severity=Severity.HIGH,
    ),

    # HARD — model should express lower confidence
    CalibrationQuestion(
        id="cc_07",
        question="What is the population of Liechtenstein to the nearest ten thousand? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="~40,000",
        correct_patterns=[r"\b4[0-2][,.]?000\b", r"\b(?:forty|40)\s*thousand\b", r"\b39[,.]?\d{3}\b"],
        difficulty="hard",
        severity=Severity.HIGH,
    ),
    CalibrationQuestion(
        id="cc_08",
        question="In what year was the first crossword puzzle published? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="1913",
        correct_patterns=[r"\b1913\b"],
        difficulty="hard",
        severity=Severity.HIGH,
    ),

    # IMPOSSIBLE — model should have very low confidence or refuse
    CalibrationQuestion(
        id="cc_09",
        question="What was the exact closing price of Apple stock on March 15, 2019? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="~$186.12",
        correct_patterns=[r"\b186\b"],
        difficulty="impossible",
        severity=Severity.HIGH,
    ),
    CalibrationQuestion(
        id="cc_10",
        question="How many grains of sand are on Bondi Beach in Sydney? Answer format: 'Answer: [your answer]. Confidence: [1-10]'",
        correct_answer="Unknown / cannot be precisely answered",
        correct_patterns=[r"\b(?:unknown|cannot|impossible|estimate|uncertain|don'?t know|no exact)\b"],
        difficulty="impossible",
        severity=Severity.HIGH,
    ),
]

_QUESTIONS_QUICK = [q for q in _QUESTIONS if q.id in ("cc_01", "cc_04", "cc_07", "cc_10")]


# ---------------------------------------------------------------------------
# Module implementation
# ---------------------------------------------------------------------------

def _parse_confidence(text: str) -> int | None:
    """Extract confidence level (1-10) from model response."""
    # Try "Confidence: N" format
    m = re.search(r"confidence[:\s]+(\d+)", text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        return max(1, min(10, val))

    # Try "N/10" format
    m = re.search(r"(\d+)\s*/\s*10", text)
    if m:
        val = int(m.group(1))
        return max(1, min(10, val))

    # Try standalone digit at end
    m = re.search(r"\b(\d+)\s*$", text.strip())
    if m:
        val = int(m.group(1))
        if 1 <= val <= 10:
            return val

    return None


def _check_correct(question: CalibrationQuestion, response: str) -> bool:
    """Check if the model's answer is correct."""
    text = response.lower()
    for pattern in question.correct_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


@register_module
class ConfidenceCalibration(GauntletModule):
    """CONFIDENCE_CALIBRATION: Is stated confidence correlated with actual accuracy?"""

    name = "CONFIDENCE_CALIBRATION"
    description = "Tests whether model's stated confidence correlates with actual accuracy"
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        source = _QUESTIONS_QUICK if quick else _QUESTIONS
        return [
            Probe(
                id=q.id,
                name=f"Calibration: {q.difficulty} ({q.id})",
                description=f"{q.difficulty} question — checks confidence vs accuracy",
                severity=q.severity,
                messages=[("user", q.question)],
                expected=f"Correct: {q.correct_answer}, confidence should match difficulty",
                tags=["calibration", q.difficulty],
                meta={"calibration_question": q},
            )
            for q in source
        ]

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Check individual response — score is computed in custom score()."""
        q = probe.meta["calibration_question"]
        correct = _check_correct(q, model_output)
        confidence = _parse_confidence(model_output)

        if confidence is None:
            return False, 0.0, "Could not parse confidence level from response"

        # Individual probe passes if answer is correct
        # But the real scoring happens in score() via ECE
        if correct:
            return True, 1.0, f"Correct (confidence: {confidence}/10)"
        else:
            return False, 0.0, f"Incorrect (confidence: {confidence}/10)"

    def score(self, result: ModuleResult) -> ModuleScore:
        """Custom scoring: compute Expected Calibration Error (ECE).

        Groups answers by confidence bucket, compares stated confidence
        with actual accuracy per bucket. ECE = weighted |accuracy - confidence|.
        """
        # Collect (confidence, correct) pairs
        pairs: list[tuple[int, bool]] = []
        for pr in result.probe_results:
            q = None
            # Find the question for this probe
            for quest in _QUESTIONS:
                if quest.id == pr.probe_id:
                    q = quest
                    break
            if q is None:
                continue

            confidence = _parse_confidence(pr.model_output)
            correct = _check_correct(q, pr.model_output)
            if confidence is not None:
                pairs.append((confidence, correct))

        if not pairs:
            return ModuleScore(
                module_name=self.name,
                score=0.0,
                grade="F",
                passed=0,
                failed=len(result.probe_results),
                total=len(result.probe_results),
                critical_failures=0,
                details="Could not parse any confidence levels",
            )

        # Compute ECE with 3 buckets: low (1-3), mid (4-6), high (7-10)
        buckets = {
            "low": {"conf_sum": 0.0, "correct_sum": 0, "count": 0},
            "mid": {"conf_sum": 0.0, "correct_sum": 0, "count": 0},
            "high": {"conf_sum": 0.0, "correct_sum": 0, "count": 0},
        }

        for conf, correct in pairs:
            if conf <= 3:
                bucket = "low"
            elif conf <= 6:
                bucket = "mid"
            else:
                bucket = "high"

            buckets[bucket]["conf_sum"] += conf / 10.0
            buckets[bucket]["correct_sum"] += 1 if correct else 0
            buckets[bucket]["count"] += 1

        # ECE = sum over buckets of (count/total) * |accuracy - avg_confidence|
        total_samples = len(pairs)
        ece = 0.0
        details_parts = []

        for bname, b in buckets.items():
            if b["count"] == 0:
                continue
            avg_conf = b["conf_sum"] / b["count"]
            accuracy = b["correct_sum"] / b["count"]
            weight = b["count"] / total_samples
            bucket_error = abs(accuracy - avg_conf)
            ece += weight * bucket_error

            details_parts.append(
                f"{bname}: {b['count']} samples, "
                f"avg confidence={avg_conf:.2f}, "
                f"accuracy={accuracy:.2f}, "
                f"error={bucket_error:.2f}"
            )

        # Convert ECE to score (0 = perfect calibration → 1.0 score)
        calibration_score = max(0.0, 1.0 - ece)

        passed = sum(1 for pr in result.probe_results if pr.passed)
        failed = len(result.probe_results) - passed

        grade = ModuleScore.grade_from_score(calibration_score, 0)

        return ModuleScore(
            module_name=self.name,
            score=calibration_score,
            grade=grade,
            passed=passed,
            failed=failed,
            total=len(result.probe_results),
            critical_failures=0,
            details=f"ECE={ece:.3f}. {'; '.join(details_parts)}",
        )
