"""Tests for the perplexity baseline module."""
from __future__ import annotations

import math
import pytest

from gauntlet.core.modules.perplexity_baseline import (
    PerplexityBaseline,
    compute_perplexity,
    EVAL_CORPUS,
    EVAL_PROMPT,
)
from gauntlet.core.modules.base import ModuleScore, Severity
from gauntlet.core.scorer import compute_gauntlet_score
from gauntlet.core.trust_score import _EXCLUDED_MODULES


# ---------------------------------------------------------------------------
# compute_perplexity math
# ---------------------------------------------------------------------------

class TestComputePerplexity:
    """Core perplexity computation."""

    def test_known_values(self):
        """Verify perplexity formula: exp(-1/N * sum(log_probs))."""
        log_probs = [-0.5, -0.3, -0.8, -0.2, -1.0]
        expected = math.exp(-sum(log_probs) / len(log_probs))
        result = compute_perplexity(log_probs)
        assert abs(result - expected) < 1e-6

    def test_perfect_prediction(self):
        """Log prob 0 = certainty = perplexity 1."""
        assert compute_perplexity([-0.0]) == 1.0
        assert compute_perplexity([0.0, 0.0, 0.0]) == 1.0

    def test_empty_returns_inf(self):
        """No tokens = infinite perplexity."""
        assert compute_perplexity([]) == float("inf")

    def test_high_entropy(self):
        """Very negative log probs = high perplexity."""
        result = compute_perplexity([-10.0] * 10)
        assert result > 1000

    def test_single_token(self):
        """Single token perplexity = exp(-log_prob)."""
        lp = -2.3
        expected = math.exp(-lp)
        assert abs(compute_perplexity([lp]) - expected) < 1e-6

    def test_monotonic_with_entropy(self):
        """Lower log probs should produce higher perplexity."""
        ppl_low = compute_perplexity([-0.1] * 20)
        ppl_high = compute_perplexity([-3.0] * 20)
        assert ppl_low < ppl_high


# ---------------------------------------------------------------------------
# Module structure
# ---------------------------------------------------------------------------

class TestPerplexityBaselineModule:
    """Module registration, probes, and scoring metadata."""

    def test_module_name(self):
        mod = PerplexityBaseline()
        assert mod.name == "PERPLEXITY_BASELINE"

    def test_is_not_scoring_module(self):
        mod = PerplexityBaseline()
        assert mod.is_scoring_module is False

    def test_single_probe(self):
        probes = PerplexityBaseline().build_probes()
        assert len(probes) == 1
        assert probes[0].id == "ppl_01"
        assert probes[0].severity == Severity.LOW

    def test_probe_has_eval_corpus_meta(self):
        probes = PerplexityBaseline().build_probes()
        assert "eval_corpus" in probes[0].meta
        assert probes[0].meta["eval_corpus"] == EVAL_CORPUS

    def test_quick_mode_same_as_full(self):
        """Perplexity is always 1 probe regardless of mode."""
        full = PerplexityBaseline().build_probes(quick=False)
        quick = PerplexityBaseline().build_probes(quick=True)
        assert len(full) == len(quick) == 1

    def test_eval_corpus_not_empty(self):
        assert len(EVAL_CORPUS) > 100
        assert len(EVAL_PROMPT) > 50


# ---------------------------------------------------------------------------
# Scoring exclusion
# ---------------------------------------------------------------------------

class TestPerplexityExclusion:
    """Verify perplexity doesn't contaminate behavioral scores."""

    def test_excluded_from_trust_score(self):
        assert "PERPLEXITY_BASELINE" in _EXCLUDED_MODULES

    def test_excluded_from_gauntlet_score(self):
        """A perplexity score of 0.1 alongside a behavioral score of 0.9
        should produce an overall of 0.9, not 0.5."""
        from gauntlet.core.modules.base import ModuleScore

        ppl = ModuleScore(
            module_name="PERPLEXITY_BASELINE", score=0.1, grade="F",
            passed=1, failed=0, total=1, critical_failures=0,
            high_failures=0, summary="test",
            details={"perplexity": 50.0},
        )
        real = ModuleScore(
            module_name="SYCOPHANCY_TRAP", score=0.9, grade="A",
            passed=9, failed=1, total=10, critical_failures=0,
            high_failures=0, summary="test",
        )
        gs = compute_gauntlet_score("test-model", [ppl, real], "raw")
        assert abs(gs.overall_score - 0.9) < 0.01, (
            f"Perplexity leaked into score! Got {gs.overall_score}, expected ~0.9"
        )

    def test_perplexity_score_details(self):
        """Score method should include raw perplexity in details."""
        from gauntlet.core.modules.base import ModuleResult, ProbeResult

        mod = PerplexityBaseline()
        result = ModuleResult(
            module_name=mod.name,
            module_version=mod.version,
            model="test",
            probe_results=[
                ProbeResult(
                    probe_id="ppl_01", probe_name="Corpus perplexity",
                    passed=True, score=1.0, severity=Severity.LOW,
                    model_output="test", expected="test",
                    reason="Perplexity: 5.00",
                    meta={"perplexity": 5.0, "token_count": 100, "skipped": False},
                )
            ],
        )
        score = mod.score(result)
        assert score.details["perplexity"] == 5.0
        assert score.details["skipped"] is False
        assert score.grade != "?"  # Should have a real grade

    def test_skipped_score_returns_question_grade(self):
        """When logprobs aren't available, grade should be '?'."""
        from gauntlet.core.modules.base import ModuleResult, ProbeResult

        mod = PerplexityBaseline()
        result = ModuleResult(
            module_name=mod.name, module_version=mod.version, model="test",
            probe_results=[
                ProbeResult(
                    probe_id="ppl_01", probe_name="Corpus perplexity",
                    passed=False, score=0.0, severity=Severity.LOW,
                    model_output="n/a", expected="test",
                    reason="Logprobs not available",
                    meta={"perplexity": None, "skipped": True},
                )
            ],
        )
        score = mod.score(result)
        assert score.grade == "?"
        assert score.details["skipped"] is True
