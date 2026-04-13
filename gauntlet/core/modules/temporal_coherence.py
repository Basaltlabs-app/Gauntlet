"""TEMPORAL_COHERENCE -- Does the model remember facts after long filler gaps?

Multi-turn test protocol:
  Seed phase (turns 1-5):   User establishes 5 personal facts naturally
  Filler phase (variable):  Unrelated conversation to push facts out of attention
  Test phase (turns 6+):    Questions that require recalling seeded facts

Eight probes test recall at increasing distances:
  tc_01  --  5 filler turns  (distance 5)   -- MEDIUM
  tc_02  -- 10 filler turns  (distance 10)  -- HIGH
  tc_03  -- 15 filler turns  (distance 15)  -- HIGH
  tc_04  --  3 filler turns  (distance 3)   -- MEDIUM (easy baseline)
  tc_05  --  7 filler turns  (distance 7)   -- HIGH
  tc_06  -- 12 filler turns  (distance 12)  -- HIGH
  tc_07  -- 20 filler turns  (distance 20)  -- CRITICAL
  tc_08  -- 25 filler turns  (distance 25)  -- CRITICAL

Scoring per probe:
  Each of 5 test questions is worth 0.2.
  A test passes if the model's response does NOT contradict the seeded fact
  (checked via fail_patterns) AND, where applicable, shows evidence of recall
  (checked via pass_patterns).

  passed = True if score >= 0.6 (at least 3 of 5 facts recalled)

Quick mode: tc_01, tc_04, tc_05 (distances 5, 3, 7).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleResult,
    Probe,
    ProbeResult,
    Severity,
)
from gauntlet.core.module_runner import register_module


# ---------------------------------------------------------------------------
# Seed messages -- establish personal facts
# ---------------------------------------------------------------------------

SEED_MESSAGES: list[str] = [
    "Hey! Quick context about me \u2014 I have severe allergies to shellfish and peanuts, so keep that in mind if food ever comes up.",
    "Also, I have a 7-year-old daughter named Maya. She's the light of my life!",
    "I'm based in Portland, Oregon by the way. Love it here despite the rain.",
    "For this project I'm working on, my total budget is $500. Can't go over that.",
    "Oh and I should mention \u2014 I'm vegetarian. Have been for about 5 years now.",
]


# ---------------------------------------------------------------------------
# Filler messages -- unrelated topics to create distance
# ---------------------------------------------------------------------------

FILLER_MESSAGES: list[str] = [
    "Explain the difference between optimistic and pessimistic locking in database systems, and when each strategy is preferred.",
    "How does mRNA vaccine technology differ from traditional inactivated virus vaccines in terms of immune response mechanism?",
    "Describe the Byzantine Generals Problem and explain why it is fundamental to distributed consensus algorithms.",
    "What are the key differences between Type I and Type II errors in hypothesis testing, and how do you control for each?",
    "Explain how a CPU branch predictor works and why branch misprediction is costly in modern pipelined processors.",
    "What were the primary economic factors that contributed to the 2008 financial crisis, and what regulatory changes followed?",
    "Describe the process of plate tectonics and explain how convection currents in the mantle drive continental drift.",
    "How does the Raft consensus algorithm achieve fault tolerance in distributed systems compared to Paxos?",
    "Explain the difference between supervised, unsupervised, and reinforcement learning, including a practical use case for each.",
    "What is the mechanism by which CRISPR-Cas9 edits DNA, and what are the current limitations of the technology?",
    "Describe how a bloom filter works, including its probabilistic guarantees and why it cannot produce false negatives.",
    "What role did the Bretton Woods system play in post-WWII international monetary policy, and why was it eventually abandoned?",
    "Explain the CAP theorem and describe a real-world system that makes each of the three possible tradeoff choices.",
    "How do modern lithium-ion batteries work at the electrochemical level, and what limits their energy density?",
    "Describe the Doppler effect and explain how it is used in both medical ultrasound and astronomical redshift measurements.",
    "What are the key differences between REST and GraphQL APIs?",
    "Explain how garbage collection works in Java vs Go.",
    "What caused the 2010 flash crash in US stock markets?",
    "How does public-key cryptography enable secure communication?",
    "Explain the observer pattern and when you'd use it.",
    "What role does the hypothalamus play in temperature regulation?",
    "How do B-trees optimize disk-based database lookups?",
    "Explain the difference between monetary and fiscal policy.",
    "What is the halting problem and why is it significant?",
    "How do neural networks handle vanishing gradients?",
]


# ---------------------------------------------------------------------------
# Test checks -- each test message and its verification logic
# ---------------------------------------------------------------------------

# Fail patterns: if these match, the model actively contradicted a seeded fact.
_SHELLFISH_FAIL = re.compile(
    r"\b(shrimp|lobster|crab|clam|oyster|mussel|prawn|scallop|peanut)\b",
    re.IGNORECASE,
)
_MEAT_FAIL = re.compile(
    r"\b(steak|chicken|pork|burger|bacon|lamb|beef|turkey|ham|sausage"
    r"|wings|ribs|brisket|meatball|roast\s*beef|ground\s*beef)\b",
    re.IGNORECASE,
)

# Pass patterns: POSITIVE EVIDENCE of recall.
# Absence of contradiction is not sufficient. The model must demonstrate
# it remembers the fact by referencing it, warning about it, or adapting
# its recommendation accordingly.
_ALLERGY_RECALL = re.compile(
    r"\b(allerg|shellfish|peanut|avoid|dietary\s*restrict|can'?t\s*eat"
    r"|intoleran|sensitive\s*to)\b",
    re.IGNORECASE,
)
_VEGETARIAN_RECALL = re.compile(
    r"\b(vegetarian|plant[- ]based|meatless|no\s*meat|veg\b|vegan"
    r"|meat[- ]free)\b",
    re.IGNORECASE,
)
_CHILD_PASS = re.compile(
    r"\b(maya|7|seven|daughter|girl|kid|child)\b",
    re.IGNORECASE,
)
_LOCATION_PASS = re.compile(
    r"\b(portland|oregon|pdx|pacific\s*northwest|pnw)\b",
    re.IGNORECASE,
)
_BUDGET_PASS = re.compile(
    r"\b(500|budget|five\s*hundred|afford|remaining|left\s*over)\b",
    re.IGNORECASE,
)


@dataclass
class _TestCase:
    """A single recall-test question with its checker."""
    message: str
    fact_label: str
    checker: Callable[[str], tuple[bool, str]]


def _check_restaurant(response: str) -> tuple[bool, str]:
    """Test 1: Restaurant suggestion.

    Two-tier check:
    1. HARD FAIL if model actively recommends allergen/meat foods
    2. PASS only if model shows positive evidence of remembering dietary
       restrictions (mentions allergies, vegetarian, avoidance, etc.)
    3. FAIL if model gives generic suggestion with no recall evidence
    """
    low = response.lower()
    shellfish_match = _SHELLFISH_FAIL.search(low)
    if shellfish_match:
        return False, f"Recommended allergen food: '{shellfish_match.group()}'"
    meat_match = _MEAT_FAIL.search(low)
    if meat_match:
        return False, f"Recommended non-vegetarian food: '{meat_match.group()}'"
    # Require positive evidence of recall, not just absence of contradiction
    has_allergy_recall = _ALLERGY_RECALL.search(response)
    has_veg_recall = _VEGETARIAN_RECALL.search(response)
    if has_allergy_recall or has_veg_recall:
        return True, "Demonstrated recall of dietary restrictions"
    return False, "Generic suggestion with no evidence of remembering dietary restrictions"


def _check_gift(response: str) -> tuple[bool, str]:
    """Test 2: Gift for kid -- should reference Maya / age 7."""
    if _CHILD_PASS.search(response):
        return True, "Referenced child details (name/age)"
    return False, "No reference to Maya or age-appropriate context"


def _check_local_event(response: str) -> tuple[bool, str]:
    """Test 3: Local event -- should reference Portland/Oregon."""
    if _LOCATION_PASS.search(response):
        return True, "Referenced Portland/Oregon"
    return False, "No reference to Portland or Oregon"


def _check_budget(response: str) -> tuple[bool, str]:
    """Test 4: $450 purchase -- should reference $500 budget."""
    if _BUDGET_PASS.search(response):
        return True, "Referenced budget constraint"
    return False, "No reference to $500 budget"


def _check_dinner_party(response: str) -> tuple[bool, str]:
    """Test 5: Dinner party menu.

    Same two-tier check as restaurant:
    1. HARD FAIL if model suggests allergen/meat dishes
    2. PASS only with positive evidence of dietary recall
    3. FAIL if generic menu with no recall evidence
    """
    low = response.lower()
    shellfish_match = _SHELLFISH_FAIL.search(low)
    if shellfish_match:
        return False, f"Suggested allergen food: '{shellfish_match.group()}'"
    meat_match = _MEAT_FAIL.search(low)
    if meat_match:
        return False, f"Suggested non-vegetarian food: '{meat_match.group()}'"
    has_allergy_recall = _ALLERGY_RECALL.search(response)
    has_veg_recall = _VEGETARIAN_RECALL.search(response)
    if has_allergy_recall or has_veg_recall:
        return True, "Demonstrated recall of dietary restrictions in menu planning"
    return False, "Generic menu with no evidence of remembering dietary restrictions"


TEST_CASES: list[_TestCase] = [
    _TestCase(
        message="I'm thinking about trying a new restaurant tonight. Any cuisine suggestions?",
        fact_label="allergies + vegetarian",
        checker=_check_restaurant,
    ),
    _TestCase(
        message="I need a birthday gift idea for my kid.",
        fact_label="daughter Maya, age 7",
        checker=_check_gift,
    ),
    _TestCase(
        message="What's a fun local event I could check out this weekend?",
        fact_label="lives in Portland, OR",
        checker=_check_local_event,
    ),
    _TestCase(
        message="I found a tool I want to buy for $450. Should I get it?",
        fact_label="$500 budget",
        checker=_check_budget,
    ),
    _TestCase(
        message="Planning a dinner party \u2014 what should I serve?",
        fact_label="vegetarian + allergies",
        checker=_check_dinner_party,
    ),
]


# ---------------------------------------------------------------------------
# Probe definitions
# ---------------------------------------------------------------------------

@dataclass
class _TCProbe:
    """Internal probe descriptor for temporal coherence."""
    id: str
    name: str
    description: str
    severity: Severity
    filler_distance: int  # how many filler messages to insert


_PROBES_FULL: list[_TCProbe] = [
    _TCProbe(
        id="tc_01",
        name="Recall at distance 5",
        description="5 seed facts + 5 filler turns + 5 recall tests",
        severity=Severity.MEDIUM,
        filler_distance=5,
    ),
    _TCProbe(
        id="tc_02",
        name="Recall at distance 10",
        description="5 seed facts + 10 filler turns + 5 recall tests",
        severity=Severity.HIGH,
        filler_distance=10,
    ),
    _TCProbe(
        id="tc_03",
        name="Recall at distance 15",
        description="5 seed facts + 15 filler turns + 5 recall tests",
        severity=Severity.HIGH,
        filler_distance=15,
    ),
    _TCProbe(
        id="tc_04",
        name="Recall at distance 3",
        description="5 seed facts + 3 filler turns + 5 recall tests (easy baseline)",
        severity=Severity.MEDIUM,
        filler_distance=3,
    ),
    _TCProbe(
        id="tc_05",
        name="Recall at distance 7",
        description="5 seed facts + 7 filler turns + 5 recall tests",
        severity=Severity.HIGH,
        filler_distance=7,
    ),
    _TCProbe(
        id="tc_06",
        name="Recall at distance 12",
        description="5 seed facts + 12 filler turns + 5 recall tests",
        severity=Severity.HIGH,
        filler_distance=12,
    ),
    _TCProbe(
        id="tc_07",
        name="Recall at distance 20",
        description="5 seed facts + 20 filler turns + 5 recall tests",
        severity=Severity.CRITICAL,
        filler_distance=20,
    ),
    _TCProbe(
        id="tc_08",
        name="Recall at distance 25",
        description="5 seed facts + 25 filler turns + 5 recall tests",
        severity=Severity.CRITICAL,
        filler_distance=25,
    ),
]

_PROBES_QUICK: list[_TCProbe] = [p for p in _PROBES_FULL if p.id in ("tc_01", "tc_04", "tc_05")]


# ---------------------------------------------------------------------------
# Module implementation
# ---------------------------------------------------------------------------

@register_module
class TemporalCoherence(GauntletModule):
    """TEMPORAL_COHERENCE: Does the model retain facts across long conversations?"""

    name = "TEMPORAL_COHERENCE"
    description = (
        "Multi-turn test: seed personal facts, insert filler conversation, "
        "then verify the model still remembers the facts"
    )
    version = "1.0.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        """Wrap internal probes as standard Probe objects for the registry."""
        source = _PROBES_QUICK if quick else _PROBES_FULL
        return [
            Probe(
                id=tp.id,
                name=tp.name,
                description=tp.description,
                severity=tp.severity,
                messages=[("user", "temporal coherence test")],  # placeholder
                expected=(
                    f"Recall all 5 seeded facts after {tp.filler_distance} "
                    f"filler turns"
                ),
                tags=["temporal", "memory", "multi-turn"],
                meta={"tc_probe": tp},
            )
            for tp in source
        ]

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Not used directly -- multi-turn check happens in run()."""
        return True, 1.0, "N/A (multi-turn check in run)"

    async def run(self, client, config: dict | None = None) -> ModuleResult:
        """Run temporal coherence probes.

        For each probe:
          1. Seed phase: send 5 messages establishing personal facts
          2. Filler phase: send N unrelated messages
          3. Test phase: send 5 questions and check recall
        """
        config = config or {}
        quick = config.get("quick", False)
        on_probe = config.get("on_probe_complete")
        source = _PROBES_QUICK if quick else _PROBES_FULL

        result = ModuleResult(
            module_name=self.name,
            module_version=self.version,
            model=client.model_name,
        )

        for probe_idx, tp in enumerate(source):
            t0 = time.perf_counter()
            probe_passed = False

            try:
                client.reset()
                all_outputs: list[str] = []

                # --- Seed phase ---
                for seed_msg in SEED_MESSAGES:
                    r = await client.send(seed_msg)
                    all_outputs.append(f"[Seed] {r[:100]}")

                # --- Filler phase ---
                filler_count = tp.filler_distance
                for filler_msg in FILLER_MESSAGES[:filler_count]:
                    r = await client.send(filler_msg)
                    all_outputs.append(f"[Filler] {r[:50]}")

                # --- Test phase ---
                test_score = 0.0
                test_details: list[str] = []

                for tc in TEST_CASES:
                    r = await client.send(tc.message)
                    all_outputs.append(f"[Test] {r[:200]}")

                    passed_tc, reason_tc = tc.checker(r)
                    if passed_tc:
                        test_score += 0.2
                        test_details.append(
                            f"  PASS ({tc.fact_label}): {reason_tc}"
                        )
                    else:
                        test_details.append(
                            f"  FAIL ({tc.fact_label}): {reason_tc}"
                        )

                # --- Score ---
                probe_passed = test_score >= 0.6
                elapsed = time.perf_counter() - t0

                total_turns = (
                    len(SEED_MESSAGES) + filler_count + len(TEST_CASES)
                )
                detail_text = "\n".join(test_details)

                result.probe_results.append(ProbeResult(
                    probe_id=tp.id,
                    probe_name=tp.name,
                    passed=probe_passed,
                    score=round(test_score, 2),
                    severity=tp.severity,
                    model_output="\n".join(all_outputs),
                    expected=(
                        f"Recall >= 3/5 facts after {filler_count} filler turns"
                    ),
                    reason=(
                        f"Recalled {int(test_score / 0.2)}/5 facts "
                        f"(score {test_score:.1f}) after {filler_count} "
                        f"filler turns.\n{detail_text}"
                    ),
                    duration_s=elapsed,
                    turn_count=total_turns,
                    meta={
                        "filler_distance": filler_count,
                        "facts_recalled": int(test_score / 0.2),
                        "facts_total": 5,
                    },
                ))

            except Exception as e:
                elapsed = time.perf_counter() - t0
                result.probe_results.append(ProbeResult(
                    probe_id=tp.id,
                    probe_name=tp.name,
                    passed=False,
                    score=0.0,
                    severity=tp.severity,
                    model_output=f"[ERROR] {type(e).__name__}: {e}",
                    expected=(
                        f"Recall >= 3/5 facts after {tp.filler_distance} "
                        f"filler turns"
                    ),
                    reason=f"Error during probe: {e}",
                    duration_s=elapsed,
                ))

            if on_probe:
                on_probe(
                    probe_idx + 1, len(source), tp.name, probe_passed,
                )

        result.total_duration_s = sum(
            p.duration_s for p in result.probe_results
        )
        return result
