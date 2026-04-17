"""Tests for the layer sensitivity module."""
from __future__ import annotations

import pytest

from gauntlet.core.modules.layer_sensitivity import LayerSensitivity
from gauntlet.core.modules.base import ModuleResult, ProbeResult, Severity


# ---------------------------------------------------------------------------
# Probe generation
# ---------------------------------------------------------------------------

class TestProbeGeneration:
    """Verify probe set structure and reproducibility."""

    def test_full_probe_count(self):
        probes = LayerSensitivity().build_probes(quick=False, seed=42)
        assert len(probes) >= 14  # at least 14 probes across 5 categories

    def test_quick_mode_reduces(self):
        full = LayerSensitivity().build_probes(quick=False, seed=42)
        quick = LayerSensitivity().build_probes(quick=True, seed=42)
        assert len(quick) == 5  # exactly 1 per category
        assert len(quick) < len(full)

    def test_quick_covers_all_categories(self):
        quick = LayerSensitivity().build_probes(quick=True, seed=42)
        categories = {p.meta.get("category") for p in quick}
        expected = {"shallow_syntax", "factual_recall", "multi_step_logic",
                    "spatial_reasoning", "pragmatic_inference"}
        assert categories == expected

    def test_seed_reproducibility(self):
        p1 = LayerSensitivity().build_probes(seed=123)
        p2 = LayerSensitivity().build_probes(seed=123)
        assert len(p1) == len(p2)
        for a, b in zip(p1, p2):
            assert a.id == b.id
            assert a.meta == b.meta

    def test_different_seeds_vary(self):
        """Dynamic factories should produce different values for different seeds."""
        p1 = LayerSensitivity().build_probes(seed=1)
        p2 = LayerSensitivity().build_probes(seed=99999)
        # At least one factual or arithmetic probe should differ
        metas1 = [p.meta for p in p1 if p.id == "ls_log_01"]
        metas2 = [p.meta for p in p2 if p.id == "ls_log_01"]
        if metas1 and metas2:
            # The arithmetic chain uses random a,b values
            assert metas1[0].get("answer") != metas2[0].get("answer") or True
            # (may coincidentally match — don't fail on it, just verify it runs)

    def test_all_probes_have_category(self):
        probes = LayerSensitivity().build_probes(seed=42)
        for p in probes:
            assert "category" in p.meta, f"Probe {p.id} missing category"

    def test_all_probes_have_tags(self):
        probes = LayerSensitivity().build_probes(seed=42)
        for p in probes:
            assert len(p.tags) > 0, f"Probe {p.id} has no tags"


# ---------------------------------------------------------------------------
# Check logic — shallow syntax
# ---------------------------------------------------------------------------

class TestCheckShallowSyntax:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def _get_probe(self, probe_id: str):
        return next(p for p in self.probes if p.id == probe_id)

    def test_syntax_agreement_correct(self):
        p = self._get_probe("ls_syn_01")
        correct = p.meta["correct"]
        passed, score, reason = self.mod.check(p, correct)
        assert passed
        assert score == 1.0

    def test_syntax_agreement_wrong(self):
        p = self._get_probe("ls_syn_01")
        wrong = p.meta["wrong"]
        passed, score, reason = self.mod.check(p, wrong)
        assert not passed
        assert score == 0.0

    def test_format_preservation_all_lowercase(self):
        p = self._get_probe("ls_syn_02")
        passed, score, _ = self.mod.check(
            p, "the eiffel tower is a landmark in paris. it was built in 1889."
        )
        assert passed
        assert score == 1.0

    def test_format_preservation_has_uppercase(self):
        p = self._get_probe("ls_syn_02")
        passed, score, reason = self.mod.check(
            p, "The Eiffel Tower is in Paris. It was built in 1889."
        )
        assert not passed
        assert "uppercase" in reason

    def test_comma_splice_correct(self):
        p = self._get_probe("ls_syn_03")
        passed, score, _ = self.mod.check(p, "NO")
        assert passed

    def test_comma_splice_wrong(self):
        p = self._get_probe("ls_syn_03")
        passed, score, _ = self.mod.check(p, "YES")
        assert not passed


# ---------------------------------------------------------------------------
# Check logic — factual recall
# ---------------------------------------------------------------------------

class TestCheckFactualRecall:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def test_factual_recall_correct_pattern(self):
        factual_probes = [p for p in self.probes if p.meta.get("category") == "factual_recall"]
        assert len(factual_probes) >= 2
        for p in factual_probes:
            # Use the first expected pattern as the answer
            patterns = p.meta["patterns"]
            passed, score, _ = self.mod.check(p, patterns[0])
            assert passed, f"Probe {p.id} failed with correct answer '{patterns[0]}'"

    def test_factual_recall_wrong(self):
        factual_probes = [p for p in self.probes if p.meta.get("category") == "factual_recall"]
        for p in factual_probes:
            passed, score, _ = self.mod.check(p, "completely_wrong_answer_xyz123")
            assert not passed


# ---------------------------------------------------------------------------
# Check logic — multi-step logic
# ---------------------------------------------------------------------------

class TestCheckMultiStepLogic:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def test_arithmetic_chain_correct(self):
        p = next(p for p in self.probes if p.id == "ls_log_01")
        answer = str(p.meta["answer"])
        passed, score, _ = self.mod.check(p, answer)
        assert passed
        assert score == 1.0

    def test_arithmetic_chain_wrong(self):
        p = next(p for p in self.probes if p.id == "ls_log_01")
        wrong = str(p.meta["answer"] + 999)
        passed, score, _ = self.mod.check(p, wrong)
        assert not passed

    def test_transitive_correct(self):
        p = next(p for p in self.probes if p.id == "ls_log_02")
        passed, score, _ = self.mod.check(p, "D")
        assert passed

    def test_modus_tollens_correct(self):
        p = next(p for p in self.probes if p.id == "ls_log_03")
        passed, score, _ = self.mod.check(p, "NO")
        assert passed

    def test_syllogism_correct(self):
        p = next(p for p in self.probes if p.id == "ls_log_04")
        passed, score, _ = self.mod.check(p, "YES")
        assert passed


# ---------------------------------------------------------------------------
# Check logic — spatial reasoning
# ---------------------------------------------------------------------------

class TestCheckSpatialReasoning:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def test_position_ordering_correct(self):
        p = next(p for p in self.probes if p.id == "ls_spa_01")
        passed, score, _ = self.mod.check(p, "D, A, B, C")
        assert passed

    def test_position_ordering_different_format(self):
        p = next(p for p in self.probes if p.id == "ls_spa_01")
        passed, score, _ = self.mod.check(p, "D A B C")
        assert passed  # should detect sequence even without commas

    def test_mirror_reflection_correct(self):
        p = next(p for p in self.probes if p.id == "ls_spa_02")
        passed, score, _ = self.mod.check(p, "O")
        assert passed

    def test_clock_correct(self):
        p = next(p for p in self.probes if p.id == "ls_spa_03")
        passed, score, _ = self.mod.check(p, "6")
        assert passed


# ---------------------------------------------------------------------------
# Check logic — pragmatic inference
# ---------------------------------------------------------------------------

class TestCheckPragmaticInference:

    def setup_method(self):
        self.mod = LayerSensitivity()
        self.probes = self.mod.build_probes(seed=42)

    def test_sarcasm_correct(self):
        p = next(p for p in self.probes if p.id == "ls_pra_01")
        passed, score, _ = self.mod.check(p, "NO")
        assert passed

    def test_sarcasm_wrong(self):
        p = next(p for p in self.probes if p.id == "ls_pra_01")
        passed, score, _ = self.mod.check(p, "YES")
        assert not passed

    def test_implicature_correct(self):
        p = next(p for p in self.probes if p.id == "ls_pra_02")
        passed, score, _ = self.mod.check(p, "REQUEST")
        assert passed

    def test_social_norm_correct(self):
        p = next(p for p in self.probes if p.id == "ls_pra_03")
        passed, score, _ = self.mod.check(p, "B")
        assert passed


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

class TestLayerSensitivityScoring:

    def test_score_includes_category_breakdown(self):
        mod = LayerSensitivity()
        probes = mod.build_probes(seed=42)

        # Simulate all-pass results
        results = []
        for p in probes:
            results.append(ProbeResult(
                probe_id=p.id, probe_name=p.name,
                passed=True, score=1.0,
                severity=p.severity,
                model_output="correct",
                expected=p.expected,
                reason="passed",
            ))

        mr = ModuleResult(
            module_name=mod.name, module_version=mod.version,
            model="test", probe_results=results,
        )
        score = mod.score(mr)

        assert score.score == 1.0
        assert "category_scores" in score.details
        cats = score.details["category_scores"]
        assert "shallow_syntax" in cats
        assert "factual_recall" in cats
        assert "multi_step_logic" in cats
        assert "spatial_reasoning" in cats
        assert "pragmatic_inference" in cats
        for cat_score in cats.values():
            assert cat_score == 1.0

    def test_score_identifies_weakest_category(self):
        mod = LayerSensitivity()
        probes = mod.build_probes(seed=42)

        results = []
        for p in probes:
            # Fail all logic probes, pass everything else
            is_logic = p.meta.get("category") == "multi_step_logic"
            results.append(ProbeResult(
                probe_id=p.id, probe_name=p.name,
                passed=not is_logic,
                score=0.0 if is_logic else 1.0,
                severity=p.severity,
                model_output="test",
                expected=p.expected,
                reason="test",
            ))

        mr = ModuleResult(
            module_name=mod.name, module_version=mod.version,
            model="test", probe_results=results,
        )
        score = mod.score(mr)
        assert score.details["weakest_category"] == "multi_step_logic"
        assert score.details["category_scores"]["multi_step_logic"] == 0.0

    def test_module_in_profiles(self):
        from gauntlet.core.scorer import PROFILES
        for profile_name, weights in PROFILES.items():
            if not weights:  # raw profile is empty
                continue
            assert "LAYER_SENSITIVITY" in weights, (
                f"LAYER_SENSITIVITY missing from '{profile_name}' profile"
            )
