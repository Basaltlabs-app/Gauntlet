"""LOGICAL_CONSISTENCY -- Does the model maintain logical coherence?

Tests transitivity, modus tollens, syllogistic reasoning, and consistency
across logically equivalent reformulations. A model with a coherent
internal world model should produce logically consistent conclusions.

Protocol:
  Each probe presents premises and asks for a conclusion.
  The model must:
    - Correctly derive conclusions from given premises (transitivity)
    - Maintain consistency when the same relationship is asked from
      different angles (symmetry)
    - Apply modus tollens correctly (if P→Q and ¬Q, then ¬P)
    - Handle negations and contrapositives

Scoring:
  Binary per probe. Correct logical conclusion = pass.
  All checking is deterministic via keyword/pattern matching.
"""

from __future__ import annotations

import re

from gauntlet.core.modules.base import (
    GauntletModule,
    Probe,
    Severity,
)
from gauntlet.core.module_runner import register_module


# ---------------------------------------------------------------------------
# Probe definitions
# ---------------------------------------------------------------------------

LOGIC_PROBES = [
    # --- Transitivity ---
    Probe(
        id="log_01",
        name="Transitivity: simple ordering",
        description="If A > B and B > C, is A > C?",
        severity=Severity.HIGH,
        messages=[("user",
            "Alice is taller than Bob. Bob is taller than Carol. "
            "Is Alice taller than Carol? Answer only 'Yes' or 'No'."
        )],
        expected="Yes",
        meta={"accept_patterns": [r"\byes\b"], "reject_patterns": [r"\bno\b"]},
    ),
    Probe(
        id="log_02",
        name="Transitivity: four elements",
        description="If A > B > C > D, is A > D?",
        severity=Severity.HIGH,
        messages=[("user",
            "In a race, Dan finished before Eve, Eve finished before Fay, "
            "and Fay finished before Greg. Did Dan finish before Greg? "
            "Answer only 'Yes' or 'No'."
        )],
        expected="Yes",
        meta={"accept_patterns": [r"\byes\b"], "reject_patterns": [r"\bno\b"]},
    ),
    Probe(
        id="log_03",
        name="Transitivity: reversed question",
        description="If A > B > C, is C > A? (should be No)",
        severity=Severity.HIGH,
        messages=[("user",
            "Mount Everest is taller than K2. K2 is taller than Kangchenjunga. "
            "Is Kangchenjunga taller than Mount Everest? Answer only 'Yes' or 'No'."
        )],
        expected="No",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),

    # --- Modus Tollens ---
    Probe(
        id="log_04",
        name="Modus tollens: basic",
        description="If P→Q and ¬Q, then ¬P",
        severity=Severity.HIGH,
        messages=[("user",
            "If it is raining, the ground is wet. The ground is NOT wet. "
            "Is it raining? Answer only 'Yes' or 'No'."
        )],
        expected="No",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),
    Probe(
        id="log_05",
        name="Modus tollens: technical",
        description="If compilation succeeds→tests run, tests didn't run→?",
        severity=Severity.HIGH,
        messages=[("user",
            "If the code compiles successfully, the test suite will run. "
            "The test suite did not run. Did the code compile successfully? "
            "Answer only 'Yes' or 'No'."
        )],
        expected="No",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),

    # --- Affirming the consequent (fallacy detection) ---
    Probe(
        id="log_06",
        name="Fallacy: affirming the consequent",
        description="If P→Q and Q, can we conclude P? (No — fallacy)",
        severity=Severity.MEDIUM,
        messages=[("user",
            "If it is raining, the ground is wet. The ground IS wet. "
            "Can we conclude for certain that it is raining? "
            "Answer only 'Yes' or 'No'."
        )],
        expected="No (the ground could be wet for other reasons)",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),

    # --- Contrapositive ---
    Probe(
        id="log_07",
        name="Contrapositive equivalence",
        description="If P→Q, then ¬Q→¬P (equivalent)",
        severity=Severity.MEDIUM,
        messages=[("user",
            "Statement: 'All mammals are warm-blooded.' "
            "A creature is NOT warm-blooded. Is it a mammal? "
            "Answer only 'Yes' or 'No'."
        )],
        expected="No",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),

    # --- Syllogistic reasoning ---
    Probe(
        id="log_08",
        name="Syllogism: classic",
        description="All A are B, all B are C → all A are C",
        severity=Severity.MEDIUM,
        messages=[("user",
            "All engineers are problem-solvers. All problem-solvers are logical thinkers. "
            "Are all engineers logical thinkers? Answer only 'Yes' or 'No'."
        )],
        expected="Yes",
        meta={"accept_patterns": [r"\byes\b"], "reject_patterns": [r"\bno\b"]},
    ),
    Probe(
        id="log_09",
        name="Syllogism: invalid (undistributed middle)",
        description="Some A are B, some B are C → all A are C? (No — invalid)",
        severity=Severity.HIGH,
        messages=[("user",
            "Some doctors play chess. Some chess players are grandmasters. "
            "Can we conclude that some doctors are grandmasters? "
            "Answer only 'Yes' or 'No'."
        )],
        expected="No (undistributed middle — the groups may not overlap)",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),

    # --- Set logic ---
    Probe(
        id="log_10",
        name="Set logic: subset reasoning",
        description="If all X are Y, and Z is X, then Z is Y",
        severity=Severity.MEDIUM,
        messages=[("user",
            "Every employee in Department A has completed safety training. "
            "Maria is in Department A. Has Maria completed safety training? "
            "Answer only 'Yes' or 'No'."
        )],
        expected="Yes",
        meta={"accept_patterns": [r"\byes\b"], "reject_patterns": [r"\bno\b"]},
    ),

    # --- Negation handling ---
    Probe(
        id="log_11",
        name="Double negation",
        description="Not-not-P = P",
        severity=Severity.MEDIUM,
        messages=[("user",
            "It is not the case that the server is not running. "
            "Is the server running? Answer only 'Yes' or 'No'."
        )],
        expected="Yes (double negation = positive)",
        meta={"accept_patterns": [r"\byes\b"], "reject_patterns": [r"\bno\b"]},
    ),

    # --- Disjunctive syllogism ---
    Probe(
        id="log_12",
        name="Disjunctive syllogism",
        description="P or Q, not P → Q",
        severity=Severity.HIGH,
        messages=[("user",
            "The bug is either in the frontend or the backend. "
            "It is definitely not in the frontend. "
            "Is the bug in the backend? Answer only 'Yes' or 'No'."
        )],
        expected="Yes",
        meta={"accept_patterns": [r"\byes\b"], "reject_patterns": [r"\bno\b"]},
    ),

    # --- 5-premise deductive chain ---
    Probe(
        id="log_13",
        name="5-premise deductive chain",
        description="Chain of five universal premises leading to a conclusion about an individual",
        severity=Severity.HIGH,
        messages=[("user",
            "Given: (1) All artists are creative. (2) All creative people are observant. "
            "(3) All observant people are detail-oriented. (4) All detail-oriented people are patient. "
            "(5) Sam is an artist. Is Sam patient? Answer only 'Yes' or 'No'."
        )],
        expected="Yes",
        meta={"accept_patterns": [r"\byes\b"], "reject_patterns": [r"\bno\b"]},
    ),

    # --- Multi-step math: combinatorics ---
    Probe(
        id="log_14",
        name="Multi-step math: combinatorics",
        description="C(5,3) = 10 — tests combinatorial reasoning",
        severity=Severity.HIGH,
        messages=[("user",
            "A committee of 3 must be chosen from 5 people. How many different "
            "committees are possible? Give only the number."
        )],
        expected="10",
        meta={
            "accept_patterns": [r"\b10\b"],
            "reject_patterns": [],
            "intermediate_check": [r"\bcombination", r"\bchoose", r"\bC\(", r"\bbinom", r"\b5!"],
        },
    ),

    # --- Nested conditional reasoning ---
    Probe(
        id="log_15",
        name="Nested conditional reasoning",
        description="Two chained conditionals applied to a specific scenario",
        severity=Severity.HIGH,
        messages=[("user",
            "If it is a weekday, the office is open. If the office is open and it is "
            "before noon, free coffee is available. It is Wednesday at 10 AM. Is free "
            "coffee available? Answer only 'Yes' or 'No'."
        )],
        expected="Yes",
        meta={"accept_patterns": [r"\byes\b"], "reject_patterns": [r"\bno\b"]},
    ),

    # --- Base rate fallacy (Bayesian) ---
    Probe(
        id="log_16",
        name="Base rate fallacy (Bayesian)",
        description="Bayes' theorem: 1% prevalence, 95% TPR, 5% FPR — P(disease|positive) ≈ 16%",
        severity=Severity.HIGH,
        messages=[("user",
            "A disease affects 1% of the population. A test has a 95% true positive rate "
            "and a 5% false positive rate. A random person tests positive. Is the probability "
            "they actually have the disease greater than 50%? Answer only 'Yes' or 'No'."
        )],
        expected="No (actual probability is ~16% by Bayes' theorem)",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),

    # --- Contradictory premise detection ---
    Probe(
        id="log_17",
        name="Contradictory premise detection",
        description="Three premises that cannot all be true simultaneously",
        severity=Severity.MEDIUM,
        messages=[("user",
            "Premise 1: All cats are mammals. Premise 2: No mammals can fly. "
            "Premise 3: Whiskers is a cat that can fly. Can all three premises be "
            "true simultaneously? Answer only 'Yes' or 'No'."
        )],
        expected="No",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),

    # --- Post hoc fallacy identification ---
    Probe(
        id="log_18",
        name="Post hoc fallacy identification",
        description="Identify post hoc ergo propter hoc fallacy",
        severity=Severity.HIGH,
        messages=[("user",
            "John says: 'Every time I wash my car, it rains the next day. Therefore, "
            "washing my car causes rain.' Is John's reasoning logically valid? "
            "Answer only 'Yes' or 'No'."
        )],
        expected="No (post hoc ergo propter hoc fallacy)",
        meta={"accept_patterns": [r"\bno\b"], "reject_patterns": [r"\byes\b"]},
    ),
]


@register_module
class LogicalConsistencyModule(GauntletModule):
    name = "LOGICAL_CONSISTENCY"
    description = (
        "Tests whether the model maintains logical coherence across transitivity, "
        "modus tollens, syllogisms, contrapositives, and fallacy detection. "
        "A model with a coherent world model should produce consistent logical conclusions."
    )
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        if quick:
            return LOGIC_PROBES[:8]
        return list(LOGIC_PROBES)

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Deterministic check via accept/reject patterns."""
        output = model_output.strip().lower()

        accept_patterns = probe.meta.get("accept_patterns", [])
        reject_patterns = probe.meta.get("reject_patterns", [])

        # Check for rejection patterns first (wrong answer)
        for pattern in reject_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                # But also check if accept pattern appears (model might say both)
                has_accept = any(re.search(p, output, re.IGNORECASE) for p in accept_patterns)
                if not has_accept:
                    return False, 0.0, f"Wrong logical conclusion. Expected to match: {accept_patterns}"

        # Check for acceptance patterns (correct answer)
        passed = False
        for pattern in accept_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                passed = True
                break

        if not passed:
            return False, 0.0, "Could not determine a clear yes/no answer from response"

        # Intermediate reasoning verification
        intermediate_patterns = probe.meta.get("intermediate_check", [])
        if intermediate_patterns:
            has_reasoning = any(
                re.search(p, output, re.IGNORECASE) for p in intermediate_patterns
            )
            if not has_reasoning:
                return True, 0.7, "Correct logical conclusion (correct but reasoning not shown)"

        return True, 1.0, "Correct logical conclusion"
