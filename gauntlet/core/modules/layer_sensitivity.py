"""Layer Sensitivity -- probe cognitive functions that map to different transformer layers.

This module targets behavioral dimensions known to be localized in different
regions of the transformer architecture. Per-tensor quantization (different
quantization levels for different layers) creates predictable patterns of
degradation: quantizing early attention layers degrades syntax differently
than quantizing late FFN layers degrades reasoning.

By testing each cognitive function independently, Gauntlet can surface:
  - WHICH capabilities break first under quantization
  - Whether a specific quant method (Q4_K_M vs Q4_K_S vs IQ4_XS) preserves
    one function at the expense of another
  - Whether per-tensor quants (BBA, EXL2) produce different error profiles
    than uniform quants

Probe categories and their approximate layer associations:
  - Shallow syntax: early layers (1-8) — grammatical agreement, formatting
  - Factual recall: mid attention layers — entity/date/number retrieval
  - Multi-step logic: late FFN layers — chained reasoning, math proofs
  - Spatial reasoning: mid-to-late attention — grid navigation, relationships
  - Pragmatic inference: late layers — sarcasm, implication, social norms

These associations are approximate — real models distribute functions across
layers in complex ways. The probes are designed to EMPIRICALLY discover which
functions degrade under quantization, not to assert a fixed layer mapping.

All scoring is deterministic (regex, pattern matching, structural checks).
No LLM-as-judge.
"""

from __future__ import annotations

import random
import re

from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleScore,
    Probe,
    ProbeResult,
    Severity,
)
from gauntlet.core.module_runner import register_module


# ---------------------------------------------------------------------------
# Probe factories (randomized per run to prevent memorization)
# ---------------------------------------------------------------------------

def _factory_syntax_agreement(seed: int) -> tuple[str, str, str]:
    """Generate a subject-verb agreement test with randomized nouns."""
    rng = random.Random(seed)
    subjects = [
        ("The box of chocolates", "is", "are"),
        ("The list of items", "is", "are"),
        ("The group of students", "was", "were"),
        ("The collection of stamps", "has", "have"),
        ("The series of events", "was", "were"),
        ("Neither the cat nor the dogs", "are", "is"),
        ("Each of the participants", "was", "were"),
        ("The team of researchers", "has", "have"),
    ]
    subj, correct, wrong = rng.choice(subjects)
    return subj, correct, wrong


def _factory_spatial_grid(seed: int) -> tuple[list[list[str]], int, int, str]:
    """Generate a small grid navigation puzzle."""
    rng = random.Random(seed)
    size = 4
    grid = [["." for _ in range(size)] for _ in range(size)]
    # Place start
    sr, sc = 0, 0
    grid[sr][sc] = "S"
    # Place end
    er, ec = size - 1, size - 1
    grid[er][ec] = "E"
    # Place 2-3 obstacles
    for _ in range(rng.randint(2, 3)):
        r, c = rng.randint(0, size - 1), rng.randint(0, size - 1)
        if grid[r][c] == ".":
            grid[r][c] = "#"
    # Describe the shortest valid direction sequence
    return grid, er, ec, "down and right"


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

@register_module
class LayerSensitivity(GauntletModule):
    """Probe cognitive functions that map to different transformer layer groups."""

    name = "LAYER_SENSITIVITY"
    description = (
        "Tests behavioral dimensions localized in different transformer layer "
        "regions: shallow syntax (early layers), factual recall (mid attention), "
        "multi-step logic (late FFN), spatial reasoning (mid-late attention), "
        "and pragmatic inference (late layers). Designed to reveal which "
        "capabilities degrade first under quantization."
    )
    version = "0.1.0"

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        s = seed if seed is not None else random.randint(0, 999999)
        probes = []

        # ── SHALLOW SYNTAX (early layers) ────────────────────────

        subj, correct, wrong = _factory_syntax_agreement(s)
        probes.append(Probe(
            id="ls_syn_01",
            name="Subject-verb agreement (complex subject)",
            description="Tests grammatical agreement with intervening phrases — stresses early-layer syntax processing.",
            severity=Severity.MEDIUM,
            messages=[
                ("system", "You are a grammar checker. Answer with ONLY the correct form of the verb. No explanation."),
                ("user", f'Which is correct? "{subj} ___ ready." Options: "{correct}" or "{wrong}". Answer with just the word.'),
            ],
            expected=correct,
            meta={"correct": correct, "wrong": wrong, "category": "shallow_syntax"},
            tags=["syntax", "early_layers"],
        ))

        probes.append(Probe(
            id="ls_syn_02",
            name="Format preservation under constraint",
            description="Tests whether the model can maintain exact formatting constraints — stresses tokenizer/early-layer attention.",
            severity=Severity.MEDIUM,
            messages=[
                ("system", "You must respond using ONLY lowercase letters. No capitals anywhere in your response."),
                ("user", "Describe the Eiffel Tower in Paris, France in exactly two sentences."),
            ],
            expected="All lowercase response, two sentences, about the Eiffel Tower",
            meta={"category": "shallow_syntax"},
            tags=["syntax", "formatting", "early_layers"],
        ))

        probes.append(Probe(
            id="ls_syn_03",
            name="Comma splice detection",
            description="Tests whether the model can identify grammatical errors — early-layer syntactic parsing.",
            severity=Severity.LOW,
            messages=[
                ("user", 'Is this sentence grammatically correct? Answer YES or NO only.\n\n"The experiment failed, the researchers tried again with new parameters."'),
            ],
            expected="NO (comma splice)",
            meta={"correct_answer": "no", "category": "shallow_syntax"},
            tags=["syntax", "early_layers"],
        ))

        # ── FACTUAL RECALL (mid attention layers) ────────────────

        rng = random.Random(s + 100)
        facts = [
            ("What is the chemical symbol for gold?", "Au", ["au"]),
            ("What is the boiling point of water in Celsius at sea level?", "100", ["100"]),
            ("How many chromosomes do humans have?", "46", ["46"]),
            ("What is the speed of light in vacuum in km/s (approximate)?", "300,000", ["300000", "300,000", "3.*10.*8", "299792"]),
        ]
        selected_facts = rng.sample(facts, min(3, len(facts)))

        for i, (question, answer, patterns) in enumerate(selected_facts):
            probes.append(Probe(
                id=f"ls_fac_{i+1:02d}",
                name=f"Factual recall: {answer}",
                description="Tests retrieval of well-known factual knowledge — stresses mid-layer attention heads.",
                severity=Severity.MEDIUM,
                messages=[
                    ("system", "Answer with just the value. No explanation, no units unless asked."),
                    ("user", question),
                ],
                expected=answer,
                meta={"patterns": patterns, "category": "factual_recall"},
                tags=["factual", "mid_layers"],
            ))

        # ── MULTI-STEP LOGIC (late FFN layers) ────────────────────

        rng_logic = random.Random(s + 200)
        a, b = rng_logic.randint(2, 9), rng_logic.randint(2, 9)
        c = a * b
        chain_result = (a + b) * 2 - 1

        probes.append(Probe(
            id="ls_log_01",
            name="Three-step arithmetic chain",
            description="Tests chained arithmetic reasoning — stresses late FFN layers that handle multi-step computation.",
            severity=Severity.HIGH,
            messages=[
                ("user", f"Calculate step by step: ({a} + {b}) × 2 - 1. Give only the final number."),
            ],
            expected=str(chain_result),
            meta={"answer": chain_result, "category": "multi_step_logic"},
            tags=["logic", "math", "late_layers"],
        ))

        probes.append(Probe(
            id="ls_log_02",
            name="Transitive inference chain",
            description="Tests logical transitivity across 4 entities — late-layer compositional reasoning.",
            severity=Severity.HIGH,
            messages=[
                ("user",
                 "If A is taller than B, B is taller than C, and C is taller than D, "
                 "who is the shortest? Answer with just the letter."),
            ],
            expected="D",
            meta={"answer": "D", "category": "multi_step_logic"},
            tags=["logic", "transitivity", "late_layers"],
        ))

        probes.append(Probe(
            id="ls_log_03",
            name="Modus tollens application",
            description="Tests formal logical reasoning (contrapositive) — late FFN compositional logic.",
            severity=Severity.HIGH,
            messages=[
                ("user",
                 "If it is raining, then the ground is wet. The ground is not wet. "
                 "Is it raining? Answer YES or NO only."),
            ],
            expected="NO",
            meta={"answer": "no", "category": "multi_step_logic"},
            tags=["logic", "modus_tollens", "late_layers"],
        ))

        probes.append(Probe(
            id="ls_log_04",
            name="Syllogism with distractor",
            description="Tests syllogistic reasoning with an irrelevant premise — late-layer compositional filtering.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 "All mammals breathe air. Whales are mammals. Fish live in water. "
                 "Do whales breathe air? Answer YES or NO only."),
            ],
            expected="YES",
            meta={"answer": "yes", "category": "multi_step_logic"},
            tags=["logic", "syllogism", "late_layers"],
        ))

        # ── SPATIAL REASONING (mid-to-late attention) ─────────────

        probes.append(Probe(
            id="ls_spa_01",
            name="Relative position inference",
            description="Tests spatial relationship reasoning — mid-to-late attention layer processing.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 "A is to the left of B. C is to the right of B. D is to the left of A. "
                 "List all four items from left to right, separated by commas."),
            ],
            expected="D, A, B, C",
            meta={"answer": "D, A, B, C", "category": "spatial_reasoning"},
            tags=["spatial", "mid_late_layers"],
        ))

        probes.append(Probe(
            id="ls_spa_02",
            name="Mirror reflection",
            description="Tests spatial transformation reasoning — mid-to-late attention.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 'If you look at the word "HELLO" in a mirror, which letter appears '
                 "first (leftmost) in the mirror image? Answer with just the letter."),
            ],
            expected="O",
            meta={"answer": "O", "category": "spatial_reasoning"},
            tags=["spatial", "mid_late_layers"],
        ))

        probes.append(Probe(
            id="ls_spa_03",
            name="Clock hand position",
            description="Tests analog spatial reasoning — mid-to-late attention pattern matching.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 "At 3:00, the minute hand points to 12 and the hour hand points to 3. "
                 "At 6:00, where does the hour hand point? Answer with just the number."),
            ],
            expected="6",
            meta={"answer": "6", "category": "spatial_reasoning"},
            tags=["spatial", "mid_late_layers"],
        ))

        # ── PRAGMATIC INFERENCE (late layers) ─────────────────────

        probes.append(Probe(
            id="ls_pra_01",
            name="Sarcasm detection",
            description="Tests understanding of non-literal meaning — late-layer pragmatic/social processing.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 'Someone says "Oh great, another Monday" in a tired voice. '
                 "Are they genuinely excited about Monday? Answer YES or NO only."),
            ],
            expected="NO",
            meta={"answer": "no", "category": "pragmatic_inference"},
            tags=["pragmatic", "sarcasm", "late_layers"],
        ))

        probes.append(Probe(
            id="ls_pra_02",
            name="Implicature understanding",
            description="Tests Gricean implicature (what is implied but not stated) — late-layer inference.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 '"Can you pass the salt?" at a dinner table. Is this person asking '
                 "about your physical ability, or requesting the salt? Answer ABILITY or REQUEST."),
            ],
            expected="REQUEST",
            meta={"answer": "request", "category": "pragmatic_inference"},
            tags=["pragmatic", "implicature", "late_layers"],
        ))

        probes.append(Probe(
            id="ls_pra_03",
            name="Social norm inference",
            description="Tests understanding of social conventions — late-layer social/pragmatic reasoning.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 "At a job interview, the interviewer asks 'Where do you see yourself in 5 years?' "
                 "Which is the more appropriate response: (A) 'I don't know, maybe on a beach somewhere' "
                 "or (B) 'I'd like to grow into a leadership role in this field.' Answer A or B only."),
            ],
            expected="B",
            meta={"answer": "B", "category": "pragmatic_inference"},
            tags=["pragmatic", "social_norms", "late_layers"],
        ))

        # ── ADDITIONAL PROBES (v2.0.2+) ─────────────────────────

        # Extra syntax: pronoun reference resolution
        probes.append(Probe(
            id="ls_syn_04",
            name="Pronoun reference resolution",
            description="Tests coreference resolution across clauses. Stresses early-layer syntactic binding.",
            severity=Severity.MEDIUM,
            messages=[
                ("user", "In the sentence 'The trophy doesn't fit in the suitcase because it is too big', "
                 "what does 'it' refer to? Answer with just 'trophy' or 'suitcase'."),
            ],
            expected="trophy",
            meta={"answer": "trophy", "category": "shallow_syntax"},
            tags=["syntax", "coreference", "early_layers"],
        ))

        # Extra syntax: word order sensitivity
        probes.append(Probe(
            id="ls_syn_05",
            name="Word order sensitivity",
            description="Tests whether the model distinguishes 'dog bites man' from 'man bites dog'. Early-layer positional encoding.",
            severity=Severity.LOW,
            messages=[
                ("user", '"The cat chased the mouse" vs "The mouse chased the cat". '
                 "In the first sentence, who is doing the chasing? Answer with just 'cat' or 'mouse'."),
            ],
            expected="cat",
            meta={"answer": "cat", "category": "shallow_syntax"},
            tags=["syntax", "word_order", "early_layers"],
        ))

        # Extra factual: date recall
        rng_extra = random.Random(s + 300)
        date_facts = [
            ("In what year did the Berlin Wall fall?", "1989", ["1989"]),
            ("What is the freezing point of water in Fahrenheit?", "32", ["32"]),
            ("How many planets are in our solar system?", "8", ["8"]),
        ]
        df = rng_extra.choice(date_facts)
        probes.append(Probe(
            id="ls_fac_04",
            name=f"Factual recall: {df[1]}",
            description="Tests date/number retrieval. Mid-layer attention.",
            severity=Severity.MEDIUM,
            messages=[("system", "Answer with just the value."), ("user", df[0])],
            expected=df[1],
            meta={"patterns": df[2], "category": "factual_recall"},
            tags=["factual", "mid_layers"],
        ))

        # Extra logic: base-rate fallacy
        probes.append(Probe(
            id="ls_log_05",
            name="Base-rate neglect detection",
            description="Tests whether the model falls for the base-rate fallacy. Late FFN probabilistic reasoning.",
            severity=Severity.HIGH,
            messages=[
                ("user",
                 "A town has 100 cabs: 85 green and 15 blue. A witness (80% accurate) says the cab "
                 "in an accident was blue. Is it more likely the cab was actually green or blue? "
                 "Answer GREEN or BLUE only."),
            ],
            expected="GREEN",
            meta={"answer": "green", "category": "multi_step_logic"},
            tags=["logic", "base_rate", "late_layers"],
        ))

        # Extra logic: negation handling
        probes.append(Probe(
            id="ls_log_06",
            name="Double negation resolution",
            description="Tests negation processing across clauses. Late-layer compositional logic.",
            severity=Severity.MEDIUM,
            messages=[
                ("user", '"It is not the case that the door is not locked." Is the door locked? Answer YES or NO only.'),
            ],
            expected="YES",
            meta={"answer": "yes", "category": "multi_step_logic"},
            tags=["logic", "negation", "late_layers"],
        ))

        # Extra spatial: rotation
        probes.append(Probe(
            id="ls_spa_04",
            name="Mental rotation",
            description="Tests mental rotation of simple shapes. Mid-to-late attention spatial processing.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 "If you rotate the letter 'N' 90 degrees clockwise, which letter does it most resemble? "
                 "Answer with just the letter."),
            ],
            expected="Z",
            meta={"answer": "Z", "category": "spatial_reasoning"},
            tags=["spatial", "rotation", "mid_late_layers"],
        ))

        # Extra spatial: relative direction
        probes.append(Probe(
            id="ls_spa_05",
            name="Relative direction after turning",
            description="Tests spatial updating after orientation change. Mid-to-late attention.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 "You are facing north. You turn right 90 degrees. You turn right 90 degrees again. "
                 "What direction are you now facing? Answer with just the direction."),
            ],
            expected="south",
            meta={"answer": "south", "category": "spatial_reasoning"},
            tags=["spatial", "direction", "mid_late_layers"],
        ))

        # Extra pragmatic: understatement
        probes.append(Probe(
            id="ls_pra_04",
            name="Understatement recognition",
            description="Tests detection of deliberate understatement. Late-layer pragmatic inference.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 "After surviving a plane crash, someone says 'Well, that was a bit inconvenient.' "
                 "Are they genuinely saying the crash was only a minor inconvenience? Answer YES or NO only."),
            ],
            expected="NO",
            meta={"answer": "no", "category": "pragmatic_inference"},
            tags=["pragmatic", "understatement", "late_layers"],
        ))

        # Extra pragmatic: indirect speech act
        probes.append(Probe(
            id="ls_pra_05",
            name="Indirect refusal detection",
            description="Tests comprehension of indirect refusal. Late-layer social pragmatic reasoning.",
            severity=Severity.MEDIUM,
            messages=[
                ("user",
                 'You invite someone to a party and they respond: "I have to wash my hair that night." '
                 "Are they genuinely declining because of hair washing, or is this a polite refusal? "
                 "Answer GENUINE or REFUSAL."),
            ],
            expected="REFUSAL",
            meta={"answer": "refusal", "category": "pragmatic_inference"},
            tags=["pragmatic", "indirect", "late_layers"],
        ))

        if quick:
            # Quick mode: 1 probe per category = 5 probes
            quick_ids = {"ls_syn_01", "ls_fac_01", "ls_log_01", "ls_spa_01", "ls_pra_01"}
            probes = [p for p in probes if p.id in quick_ids]

        return probes

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Deterministic check for each probe type."""
        output = model_output.strip()
        output_lower = output.lower()
        meta = probe.meta
        category = meta.get("category", "")

        # ── Shallow syntax checks ──
        if category == "shallow_syntax":
            if probe.id == "ls_syn_01":
                correct = meta["correct"].lower()
                wrong = meta["wrong"].lower()
                if correct in output_lower and wrong not in output_lower:
                    return True, 1.0, f"Correct verb form: '{meta['correct']}'"
                if wrong in output_lower:
                    return False, 0.0, f"Used wrong verb form: '{meta['wrong']}'"
                return False, 0.0, f"Expected '{meta['correct']}' but got: {output[:100]}"

            if probe.id == "ls_syn_02":
                has_upper = any(c.isupper() for c in output)
                has_eiffel = "eiffel" in output_lower or "tower" in output_lower
                # Count sentences (rough: split by .)
                sentences = [s.strip() for s in output.split(".") if s.strip()]
                is_two = len(sentences) == 2

                if not has_upper and has_eiffel and is_two:
                    return True, 1.0, "All lowercase, two sentences, about Eiffel Tower"
                reasons = []
                if has_upper:
                    reasons.append("contains uppercase")
                if not has_eiffel:
                    reasons.append("doesn't mention Eiffel Tower")
                if not is_two:
                    reasons.append(f"has {len(sentences)} sentences, expected 2")
                score = 0.0
                if not has_upper:
                    score += 0.5
                if has_eiffel:
                    score += 0.25
                if is_two:
                    score += 0.25
                return score >= 0.75, score, "; ".join(reasons)

            if probe.id == "ls_syn_03":
                correct = meta["correct_answer"]
                if correct in output_lower:
                    return True, 1.0, "Correctly identified comma splice"
                return False, 0.0, f"Expected NO but got: {output[:100]}"

            # Generic answer-match for additional syntax probes (ls_syn_04+)
            answer = meta.get("answer", "").lower()
            if answer and answer in output_lower:
                return True, 1.0, f"Correct: {answer}"
            if answer:
                return False, 0.0, f"Expected '{answer}' but got: {output[:100]}"

        # ── Factual recall checks ──
        if category == "factual_recall":
            patterns = meta.get("patterns", [])
            for pat in patterns:
                if re.search(pat, output, re.IGNORECASE):
                    return True, 1.0, f"Correct factual recall (matched: {pat})"
            return False, 0.0, f"Expected one of {patterns} but got: {output[:100]}"

        # ── Multi-step logic checks ──
        if category == "multi_step_logic":
            answer = str(meta.get("answer", "")).lower()
            if answer in output_lower:
                return True, 1.0, f"Correct logical answer: {answer}"
            # Check for the number in arithmetic probes
            if probe.id == "ls_log_01":
                if str(meta["answer"]) in output:
                    return True, 1.0, f"Correct arithmetic: {meta['answer']}"
            return False, 0.0, f"Expected '{answer}' but got: {output[:100]}"

        # ── Spatial reasoning checks ──
        if category == "spatial_reasoning":
            answer = meta.get("answer", "").lower()
            if answer in output_lower:
                return True, 1.0, f"Correct spatial reasoning: {answer}"
            # Partial credit for spatial order (check sequence)
            if probe.id == "ls_spa_01":
                # Check if D comes before A, A before B, B before C in output
                positions = {}
                for letter in ["d", "a", "b", "c"]:
                    pos = output_lower.find(letter)
                    if pos >= 0:
                        positions[letter] = pos
                if len(positions) == 4:
                    if positions["d"] < positions["a"] < positions["b"] < positions["c"]:
                        return True, 1.0, "Correct left-to-right ordering"
            return False, 0.0, f"Expected '{answer}' but got: {output[:100]}"

        # ── Pragmatic inference checks ──
        if category == "pragmatic_inference":
            answer = meta.get("answer", "").lower()
            if answer in output_lower:
                return True, 1.0, f"Correct pragmatic inference: {answer}"
            # Check for YES/NO variants
            if answer in ("no", "yes"):
                if answer == "no" and any(w in output_lower for w in ["no", "not", "aren't", "isn't"]):
                    return True, 1.0, "Correctly inferred negative"
                if answer == "yes" and "yes" in output_lower:
                    return True, 1.0, "Correctly inferred positive"
            return False, 0.0, f"Expected '{answer}' but got: {output[:100]}"

        return False, 0.0, f"Unknown category: {category}"

    def score(self, result: ModuleResult) -> ModuleScore:
        """Score with per-category breakdown in details."""
        from gauntlet.core.modules.base import ModuleResult

        categories: dict[str, list[float]] = {}
        critical = 0
        high = 0

        for pr in result.probe_results:
            cat = "unknown"
            # Extract category from probe meta if available
            for p in self.build_probes():
                if p.id == pr.probe_id:
                    cat = p.meta.get("category", "unknown")
                    break
            categories.setdefault(cat, []).append(pr.score)
            if not pr.passed:
                if pr.severity == Severity.CRITICAL:
                    critical += 1
                elif pr.severity == Severity.HIGH:
                    high += 1

        # Overall score: average across all probes
        all_scores = [pr.score for pr in result.probe_results]
        overall = sum(all_scores) / len(all_scores) if all_scores else 0.0

        # Per-category averages
        cat_averages = {
            cat: round(sum(scores) / len(scores), 3)
            for cat, scores in categories.items()
        }

        grade = ModuleScore.grade_from_score(overall, critical)

        # Build summary highlighting weakest category
        weakest = min(cat_averages, key=cat_averages.get) if cat_averages else "none"
        weakest_score = cat_averages.get(weakest, 0)

        return ModuleScore(
            module_name=self.name,
            score=overall,
            grade=grade,
            passed=sum(1 for pr in result.probe_results if pr.passed),
            failed=sum(1 for pr in result.probe_results if not pr.passed),
            total=len(result.probe_results),
            critical_failures=critical,
            high_failures=high,
            summary=(
                f"Layer sensitivity: {overall:.0%} overall. "
                f"Weakest: {weakest.replace('_', ' ')} ({weakest_score:.0%})"
            ),
            details={
                "category_scores": cat_averages,
                "weakest_category": weakest,
            },
        )
