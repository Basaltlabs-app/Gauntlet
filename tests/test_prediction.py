"""Tests for gauntlet.core.prediction module."""

import math

import pytest

from gauntlet.core.prediction import (
    PredictionResult,
    PerformancePredictor,
    _cosine_similarity,
    build_score_matrix_from_history,
)


# ---------------------------------------------------------------------------
# Fixtures: reusable score matrices
# ---------------------------------------------------------------------------

@pytest.fixture
def full_matrix():
    """Score matrix with multiple models across multiple tiers."""
    return {
        "qwen2.5:14b": {
            "CONSUMER_LOW": 55.0,
            "CONSUMER_MID": 72.0,
            "CONSUMER_HIGH": 85.0,
            "CLOUD": 90.0,
        },
        "llama3:8b": {
            "CONSUMER_LOW": 50.0,
            "CONSUMER_MID": 68.0,
            "CONSUMER_HIGH": 80.0,
            "CLOUD": 88.0,
        },
        "gemma2:9b": {
            "CONSUMER_LOW": 48.0,
            "CONSUMER_MID": 65.0,
            "CONSUMER_HIGH": 78.0,
            "CLOUD": 86.0,
        },
        "mistral:7b": {
            "EDGE": 30.0,
            "CONSUMER_LOW": 52.0,
            "CONSUMER_MID": 70.0,
            "CONSUMER_HIGH": 82.0,
            "CLOUD": 89.0,
        },
    }


@pytest.fixture
def sparse_matrix():
    """Score matrix with incomplete data -- models missing some tiers."""
    return {
        "model_a": {
            "CONSUMER_MID": 70.0,
            "CONSUMER_HIGH": 85.0,
            "CLOUD": 92.0,
        },
        "model_b": {
            "EDGE": 40.0,
            "CONSUMER_LOW": 60.0,
            "CONSUMER_MID": 75.0,
            "CONSUMER_HIGH": 88.0,
            "CLOUD": 93.0,
        },
        "model_c": {
            "CONSUMER_MID": 72.0,
            "CONSUMER_HIGH": 87.0,
            "CLOUD": 91.0,
        },
    }


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    """Tests for _cosine_similarity()."""

    def test_identical_vectors(self):
        """Identical vectors should have similarity ~1.0."""
        a = {"EDGE": 30.0, "CONSUMER_MID": 70.0, "CLOUD": 90.0}
        b = {"EDGE": 30.0, "CONSUMER_MID": 70.0, "CLOUD": 90.0}
        sim = _cosine_similarity(a, b)
        assert sim == pytest.approx(1.0, abs=0.001)

    def test_proportional_vectors(self):
        """Proportional vectors (same direction) should have similarity ~1.0."""
        a = {"EDGE": 10.0, "CONSUMER_MID": 20.0, "CLOUD": 30.0}
        b = {"EDGE": 20.0, "CONSUMER_MID": 40.0, "CLOUD": 60.0}
        sim = _cosine_similarity(a, b)
        assert sim == pytest.approx(1.0, abs=0.001)

    def test_orthogonal_vectors(self):
        """Orthogonal-like vectors should have low similarity."""
        # Not truly orthogonal in high-dim sense, but very different patterns
        a = {"T1": 100.0, "T2": 0.0, "T3": 0.0}
        b = {"T1": 0.0, "T2": 100.0, "T3": 0.0}
        sim = _cosine_similarity(a, b)
        assert sim == pytest.approx(0.0, abs=0.001)

    def test_empty_vectors(self):
        """Empty dicts should return 0.0."""
        assert _cosine_similarity({}, {}) == 0.0

    def test_no_common_keys(self):
        """Vectors with no common keys return 0.0."""
        a = {"T1": 50.0, "T2": 60.0}
        b = {"T3": 70.0, "T4": 80.0}
        assert _cosine_similarity(a, b) == 0.0

    def test_single_common_key(self):
        """Only one common key is insufficient (requires >=2), returns 0.0."""
        a = {"T1": 50.0, "T2": 60.0}
        b = {"T1": 70.0, "T3": 80.0}
        assert _cosine_similarity(a, b) == 0.0

    def test_zero_magnitude(self):
        """Zero-magnitude vector returns 0.0 (avoids division by zero)."""
        a = {"T1": 0.0, "T2": 0.0}
        b = {"T1": 50.0, "T2": 60.0}
        assert _cosine_similarity(a, b) == 0.0

    def test_partial_overlap(self):
        """Similarity is computed only over common keys."""
        a = {"T1": 50.0, "T2": 60.0, "T3": 70.0}
        b = {"T2": 60.0, "T3": 70.0, "T4": 80.0}
        # Common: T2 and T3 -- identical values, so similarity = 1.0
        sim = _cosine_similarity(a, b)
        assert sim == pytest.approx(1.0, abs=0.001)

    def test_negative_values(self):
        """Negative values are handled correctly (unlikely in scores but valid math)."""
        a = {"T1": -10.0, "T2": 20.0}
        b = {"T1": 10.0, "T2": -20.0}
        sim = _cosine_similarity(a, b)
        # dot = -100 + -400 = -500, mags identical, so sim = -1.0
        assert sim == pytest.approx(-1.0, abs=0.001)


# ---------------------------------------------------------------------------
# PerformancePredictor.predict — direct data
# ---------------------------------------------------------------------------

class TestPredictDirect:
    """Tests for direct data lookups."""

    def test_direct_data_returns_confidence_1(self, full_matrix):
        """When direct data exists, confidence should be 1.0."""
        predictor = PerformancePredictor(full_matrix)
        result = predictor.predict("qwen2.5:14b", "CLOUD")

        assert result.predicted_score == 90.0
        assert result.confidence == 1.0
        assert result.basis == "direct"
        assert result.prediction_tier == "CLOUD"
        assert result.similar_models == []

    def test_direct_data_rounds_score(self):
        """Score should be rounded to 1 decimal place."""
        matrix = {"model_x": {"CLOUD": 88.456}}
        predictor = PerformancePredictor(matrix)
        result = predictor.predict("model_x", "CLOUD")

        assert result.predicted_score == 88.5
        assert result.confidence == 1.0


# ---------------------------------------------------------------------------
# PerformancePredictor.predict — interpolation
# ---------------------------------------------------------------------------

class TestPredictInterpolation:
    """Tests for interpolated predictions using similar models."""

    def test_interpolation_from_similar_models(self, sparse_matrix):
        """Model missing a tier should be predicted from similar models."""
        predictor = PerformancePredictor(sparse_matrix)
        # model_a is missing EDGE and CONSUMER_LOW; model_b has them
        # model_a and model_b share CONSUMER_MID, CONSUMER_HIGH, CLOUD
        result = predictor.predict("model_a", "CONSUMER_LOW")

        assert result.basis == "interpolated" or result.basis == "extrapolated"
        if result.basis == "interpolated":
            assert result.confidence > 0.0
            assert result.confidence <= 0.95
            assert result.predicted_score > 0.0
            assert len(result.similar_models) >= 1

    def test_interpolated_never_confidence_1(self, full_matrix):
        """Interpolated results should never have confidence=1.0."""
        # qwen2.5:14b doesn't have EDGE in the fixture, so it must predict
        predictor = PerformancePredictor(full_matrix)

        result = predictor.predict("qwen2.5:14b", "EDGE")
        # It should be interpolated or extrapolated, never direct
        assert result.basis != "direct"
        if result.basis == "interpolated":
            assert result.confidence < 1.0

    def test_similar_models_sorted_by_similarity(self, full_matrix):
        """Similar models in result should be sorted by similarity descending."""
        # Remove EDGE from qwen so it must predict
        full_matrix["qwen2.5:14b"].pop("EDGE", None)
        predictor = PerformancePredictor(full_matrix)
        result = predictor.predict("qwen2.5:14b", "EDGE")

        if result.similar_models:
            sims = [m["similarity"] for m in result.similar_models]
            assert sims == sorted(sims, reverse=True)


# ---------------------------------------------------------------------------
# PerformancePredictor.predict — no data
# ---------------------------------------------------------------------------

class TestPredictNoData:
    """Tests for models with no community data."""

    def test_unknown_model_returns_zero_confidence(self, full_matrix):
        """Unknown model should return confidence=0.0."""
        predictor = PerformancePredictor(full_matrix)
        result = predictor.predict("totally_unknown_model", "CLOUD")

        assert result.predicted_score == 0.0
        assert result.confidence == 0.0
        assert result.basis == "no_data"
        assert result.sample_size == 0

    def test_empty_matrix_returns_no_data(self):
        """Empty matrix returns no_data for any query."""
        predictor = PerformancePredictor({})
        result = predictor.predict("any_model", "CLOUD")

        assert result.confidence == 0.0
        assert result.basis == "no_data"

    def test_model_with_empty_scores(self):
        """Model present in matrix but with empty dict returns no_data."""
        matrix = {"empty_model": {}}
        predictor = PerformancePredictor(matrix)
        result = predictor.predict("empty_model", "CLOUD")

        assert result.confidence == 0.0
        assert result.basis == "no_data"


# ---------------------------------------------------------------------------
# PerformancePredictor.predict — extrapolation
# ---------------------------------------------------------------------------

class TestPredictExtrapolation:
    """Tests for extrapolated predictions (no similar models found)."""

    def test_extrapolation_uses_cross_tier_average(self):
        """When no similar models exist, use the model's own cross-tier average."""
        # Only one model in the matrix -- no neighbors possible
        matrix = {
            "lonely_model": {
                "CONSUMER_MID": 70.0,
                "CONSUMER_HIGH": 80.0,
            }
        }
        predictor = PerformancePredictor(matrix)
        result = predictor.predict("lonely_model", "CLOUD")

        assert result.basis == "extrapolated"
        assert result.confidence == 0.2
        assert result.predicted_score == 75.0  # (70+80)/2
        assert result.sample_size == 2

    def test_extrapolation_low_confidence(self):
        """Extrapolated predictions always have confidence=0.2."""
        matrix = {
            "solo": {"EDGE": 40.0, "CONSUMER_LOW": 60.0},
        }
        predictor = PerformancePredictor(matrix)
        result = predictor.predict("solo", "CLOUD")

        assert result.confidence == 0.2
        assert result.basis == "extrapolated"


# ---------------------------------------------------------------------------
# PerformancePredictor.recommended_tier
# ---------------------------------------------------------------------------

class TestRecommendedTier:
    """Tests for recommended_tier()."""

    def test_finds_minimum_tier_above_threshold(self, full_matrix):
        """Should find the lowest tier where predicted score >= min_score."""
        predictor = PerformancePredictor(full_matrix)
        rec = predictor.recommended_tier("qwen2.5:14b", min_score=75.0)

        assert rec["minimum_tier"] is not None
        # qwen2.5:14b has CONSUMER_HIGH=85, which is >= 75
        # CONSUMER_MID=72, which is < 75
        assert rec["minimum_tier"] == "CONSUMER_HIGH"
        assert rec["min_score_target"] == 75.0

    def test_returns_none_when_no_tier_meets_threshold(self):
        """When all scores are below threshold, minimum_tier should be None."""
        matrix = {
            "weak_model": {
                "EDGE": 10.0,
                "CONSUMER_LOW": 20.0,
                "CONSUMER_MID": 30.0,
                "CONSUMER_HIGH": 40.0,
                "CLOUD": 50.0,
            }
        }
        predictor = PerformancePredictor(matrix)
        rec = predictor.recommended_tier("weak_model", min_score=90.0)

        assert rec["minimum_tier"] is None

    def test_predictions_dict_populated(self, full_matrix):
        """The predictions dict should contain entries for available tiers."""
        predictor = PerformancePredictor(full_matrix)
        rec = predictor.recommended_tier("qwen2.5:14b", min_score=75.0)

        assert "predictions" in rec
        assert len(rec["predictions"]) > 0
        # Each prediction entry has score, confidence, basis
        for tier_name, pred in rec["predictions"].items():
            assert "score" in pred
            assert "confidence" in pred
            assert "basis" in pred

    def test_unknown_model_returns_none_tiers(self, full_matrix):
        """Unknown model should return None for both tiers."""
        predictor = PerformancePredictor(full_matrix)
        rec = predictor.recommended_tier("unknown_model", min_score=75.0)

        assert rec["minimum_tier"] is None
        assert rec["recommended_tier"] is None

    def test_recommended_bumps_up_when_low_confidence(self):
        """If min_tier via extrapolation has low confidence, recommended should bump up."""
        # Only one model: extrapolated tiers get confidence=0.2, direct tiers get 1.0
        matrix = {
            "solo_model": {
                "CONSUMER_MID": 80.0,
                "CONSUMER_HIGH": 90.0,
            },
        }
        predictor = PerformancePredictor(matrix)
        rec = predictor.recommended_tier("solo_model", min_score=75.0)

        # Extrapolated avg = (80+90)/2 = 85 >= 75, so EDGE qualifies as min (confidence=0.2)
        # But first tier with confidence >= 0.5 is CONSUMER_MID (direct, confidence=1.0)
        assert rec["minimum_tier"] is not None
        # Recommended should be where confidence is high enough
        assert rec["recommended_tier"] == "CONSUMER_MID"


# ---------------------------------------------------------------------------
# PerformancePredictor.quantization_impact
# ---------------------------------------------------------------------------

class TestQuantizationImpact:
    """Tests for quantization_impact()."""

    def test_matching_family_and_size(self):
        """Should aggregate scores for models matching family and size."""
        matrix = {
            "llama3:8b-q4": {"CONSUMER_MID": 70.0, "CLOUD": 85.0},
            "llama3:8b-q8": {"CONSUMER_MID": 75.0, "CLOUD": 90.0},
            "llama3:8b-fp16": {"CONSUMER_MID": 80.0, "CLOUD": 92.0},
            "qwen2:7b-q4": {"CONSUMER_MID": 68.0, "CLOUD": 82.0},
        }
        predictor = PerformancePredictor(matrix)
        impact = predictor.quantization_impact("llama3", "8b")

        assert "CONSUMER_MID" in impact
        assert "CLOUD" in impact
        # Should average 3 llama3:8b variants (70+75+80)/3 = 75.0 for CONSUMER_MID
        assert impact["CONSUMER_MID"] == 75.0
        # (85+90+92)/3 = 89.0 for CLOUD
        assert impact["CLOUD"] == pytest.approx(89.0, abs=0.1)

    def test_no_matching_models(self):
        """No matching models returns empty dict."""
        matrix = {
            "qwen2:7b": {"CLOUD": 80.0},
        }
        predictor = PerformancePredictor(matrix)
        impact = predictor.quantization_impact("nonexistent", "999b")

        assert impact == {}

    def test_case_insensitive_matching(self):
        """Family and size matching should be case-insensitive."""
        matrix = {
            "Llama3:8B-Q4": {"CLOUD": 85.0},
        }
        predictor = PerformancePredictor(matrix)
        impact = predictor.quantization_impact("llama3", "8b")

        assert "CLOUD" in impact
        assert impact["CLOUD"] == 85.0


# ---------------------------------------------------------------------------
# build_score_matrix_from_history
# ---------------------------------------------------------------------------

class TestBuildScoreMatrix:
    """Tests for build_score_matrix_from_history()."""

    def test_basic_matrix_building(self):
        """Build matrix from well-formed history rows."""
        rows = [
            {"model_name": "model_a", "hardware_tier": "CLOUD", "overall_score": 90.0},
            {"model_name": "model_a", "hardware_tier": "CLOUD", "overall_score": 92.0},
            {"model_name": "model_a", "hardware_tier": "CONSUMER_MID", "overall_score": 70.0},
            {"model_name": "model_b", "hardware_tier": "CLOUD", "overall_score": 85.0},
        ]
        matrix = build_score_matrix_from_history(rows)

        assert "model_a" in matrix
        assert "model_b" in matrix
        # model_a CLOUD should be average of 90 and 92 = 91.0
        assert matrix["model_a"]["CLOUD"] == 91.0
        assert matrix["model_a"]["CONSUMER_MID"] == 70.0
        assert matrix["model_b"]["CLOUD"] == 85.0

    def test_skips_rows_without_model_name(self):
        """Rows missing model_name should be skipped."""
        rows = [
            {"model_name": "", "hardware_tier": "CLOUD", "overall_score": 90.0},
            {"hardware_tier": "CLOUD", "overall_score": 80.0},
            {"model_name": "valid", "hardware_tier": "CLOUD", "overall_score": 85.0},
        ]
        matrix = build_score_matrix_from_history(rows)

        assert len(matrix) == 1
        assert "valid" in matrix

    def test_skips_rows_without_tier(self):
        """Rows missing hardware_tier should be skipped."""
        rows = [
            {"model_name": "model_a", "hardware_tier": "", "overall_score": 90.0},
            {"model_name": "model_a", "overall_score": 80.0},
            {"model_name": "model_a", "hardware_tier": "CLOUD", "overall_score": 85.0},
        ]
        matrix = build_score_matrix_from_history(rows)

        assert matrix["model_a"]["CLOUD"] == 85.0
        assert len(matrix["model_a"]) == 1  # only CLOUD

    def test_skips_rows_without_score(self):
        """Rows with None overall_score should be skipped."""
        rows = [
            {"model_name": "model_a", "hardware_tier": "CLOUD", "overall_score": None},
            {"model_name": "model_a", "hardware_tier": "CLOUD", "overall_score": 85.0},
        ]
        matrix = build_score_matrix_from_history(rows)

        assert matrix["model_a"]["CLOUD"] == 85.0

    def test_empty_rows(self):
        """Empty input returns empty matrix."""
        assert build_score_matrix_from_history([]) == {}

    def test_score_averaging(self):
        """Multiple scores for same model+tier should be averaged and rounded."""
        rows = [
            {"model_name": "m", "hardware_tier": "T1", "overall_score": 80.0},
            {"model_name": "m", "hardware_tier": "T1", "overall_score": 90.0},
            {"model_name": "m", "hardware_tier": "T1", "overall_score": 85.0},
        ]
        matrix = build_score_matrix_from_history(rows)

        # (80+90+85)/3 = 85.0
        assert matrix["m"]["T1"] == 85.0

    def test_string_scores_converted_to_float(self):
        """Scores should be converted to float even if stored oddly."""
        rows = [
            {"model_name": "m", "hardware_tier": "T1", "overall_score": 80},  # int
        ]
        matrix = build_score_matrix_from_history(rows)
        assert isinstance(matrix["m"]["T1"], float)


# ---------------------------------------------------------------------------
# PredictionResult dataclass
# ---------------------------------------------------------------------------

class TestPredictionResult:
    """Tests for PredictionResult dataclass."""

    def test_default_notes(self):
        """Notes should default to empty string."""
        result = PredictionResult(
            predicted_score=85.0,
            confidence=0.8,
            basis="interpolated",
            similar_models=[],
            sample_size=3,
            prediction_tier="CLOUD",
        )
        assert result.notes == ""

    def test_all_fields_set(self):
        """All fields should be accessible."""
        result = PredictionResult(
            predicted_score=85.0,
            confidence=0.8,
            basis="interpolated",
            similar_models=[{"name": "m1", "score": 80.0, "similarity": 0.9}],
            sample_size=3,
            prediction_tier="CLOUD",
            notes="Test note",
        )
        assert result.predicted_score == 85.0
        assert result.confidence == 0.8
        assert result.basis == "interpolated"
        assert len(result.similar_models) == 1
        assert result.sample_size == 3
        assert result.prediction_tier == "CLOUD"
        assert result.notes == "Test note"


# ---------------------------------------------------------------------------
# Integration / edge cases
# ---------------------------------------------------------------------------

class TestIntegration:
    """Integration-level tests combining multiple components."""

    def test_end_to_end_history_to_prediction(self):
        """Build matrix from history rows and make a prediction."""
        rows = [
            {"model_name": "qwen2.5:14b", "hardware_tier": "CONSUMER_MID", "overall_score": 72.0},
            {"model_name": "qwen2.5:14b", "hardware_tier": "CONSUMER_HIGH", "overall_score": 85.0},
            {"model_name": "qwen2.5:14b", "hardware_tier": "CLOUD", "overall_score": 90.0},
            {"model_name": "llama3:8b", "hardware_tier": "CONSUMER_MID", "overall_score": 68.0},
            {"model_name": "llama3:8b", "hardware_tier": "CONSUMER_HIGH", "overall_score": 80.0},
            {"model_name": "llama3:8b", "hardware_tier": "CLOUD", "overall_score": 88.0},
            {"model_name": "llama3:8b", "hardware_tier": "CONSUMER_LOW", "overall_score": 50.0},
        ]

        matrix = build_score_matrix_from_history(rows)
        predictor = PerformancePredictor(matrix)

        # Direct lookup
        result_direct = predictor.predict("qwen2.5:14b", "CLOUD")
        assert result_direct.basis == "direct"
        assert result_direct.confidence == 1.0
        assert result_direct.predicted_score == 90.0

        # Prediction for missing tier
        result_pred = predictor.predict("qwen2.5:14b", "CONSUMER_LOW")
        # Should either interpolate or extrapolate
        assert result_pred.basis in ("interpolated", "extrapolated")
        assert result_pred.predicted_score > 0

    def test_large_matrix_performance(self):
        """Predictor handles a large matrix without error."""
        matrix = {}
        for i in range(100):
            matrix[f"model_{i}"] = {
                "EDGE": 20.0 + i * 0.5,
                "CONSUMER_LOW": 40.0 + i * 0.3,
                "CONSUMER_MID": 60.0 + i * 0.2,
                "CONSUMER_HIGH": 75.0 + i * 0.15,
                "CLOUD": 85.0 + i * 0.1,
            }

        predictor = PerformancePredictor(matrix)
        result = predictor.predict("model_50", "CLOUD")

        assert result.basis == "direct"
        assert result.confidence == 1.0

    def test_prediction_result_scores_in_valid_range(self, full_matrix):
        """All predicted scores should be within reasonable bounds."""
        predictor = PerformancePredictor(full_matrix)

        for tier in ["EDGE", "CONSUMER_LOW", "CONSUMER_MID", "CONSUMER_HIGH", "CLOUD"]:
            result = predictor.predict("qwen2.5:14b", tier)
            if result.confidence > 0:
                assert 0 <= result.predicted_score <= 100
                assert 0 <= result.confidence <= 1.0
