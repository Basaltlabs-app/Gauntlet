"""Tests for gauntlet.core.statistics module."""

import math

import pytest

from gauntlet.core.statistics import (
    MIN_RELIABLE_SAMPLE,
    ScoreStatistics,
    _percentile,
    _t_critical,
    compute_degradation,
    compute_statistics,
    detect_outliers,
)


# ---------------------------------------------------------------------------
# compute_statistics — known data
# ---------------------------------------------------------------------------

class TestComputeStatistics:
    """Tests for compute_statistics()."""

    def test_known_data(self):
        """Verify mean, median, std_dev, CI bounds with a known dataset."""
        scores = [10.0, 20.0, 30.0, 40.0, 50.0]
        stats = compute_statistics(scores)

        assert stats is not None
        assert stats.mean == 30.0
        assert stats.median == 30.0
        # Sample std dev of [10,20,30,40,50] = sqrt(250/4) = sqrt(62.5) ~ 15.81
        assert stats.std_dev == pytest.approx(15.81, abs=0.01)
        assert stats.sample_size == 5
        assert stats.min_score == 10.0
        assert stats.max_score == 50.0
        # CI should be symmetric around mean
        assert stats.ci_lower < stats.mean
        assert stats.ci_upper > stats.mean
        assert stats.confidence_level == 0.95

    def test_single_score(self):
        """n=1 returns a ScoreStatistics with all values equal to the single score."""
        stats = compute_statistics([42.0])

        assert stats is not None
        assert stats.mean == 42.0
        assert stats.median == 42.0
        assert stats.std_dev == 0.0
        assert stats.ci_lower == 42.0
        assert stats.ci_upper == 42.0
        assert stats.sample_size == 1
        assert stats.min_score == 42.0
        assert stats.max_score == 42.0
        assert stats.percentile_25 == 42.0
        assert stats.percentile_75 == 42.0
        assert stats.iqr == 0.0
        assert stats.outlier_count == 0
        assert stats.is_reliable is False

    def test_empty_list(self):
        """n=0 returns None."""
        assert compute_statistics([]) is None

    def test_uniform_data(self):
        """All identical values should produce std_dev=0 and CI collapsed to mean."""
        scores = [5.0, 5.0, 5.0, 5.0, 5.0]
        stats = compute_statistics(scores)

        assert stats is not None
        assert stats.mean == 5.0
        assert stats.median == 5.0
        assert stats.std_dev == 0.0
        assert stats.ci_lower == 5.0
        assert stats.ci_upper == 5.0
        assert stats.iqr == 0.0
        assert stats.outlier_count == 0

    def test_two_scores(self):
        """n=2 still produces valid statistics."""
        stats = compute_statistics([10.0, 20.0])

        assert stats is not None
        assert stats.mean == 15.0
        assert stats.median == 15.0
        assert stats.sample_size == 2
        # CI should be very wide with only 2 samples (t-critical for df=1 is ~12.7)
        assert stats.ci_upper - stats.ci_lower > 20.0

    def test_is_reliable_true_when_n_ge_5(self):
        """is_reliable should be True when sample_size >= MIN_RELIABLE_SAMPLE."""
        scores = list(range(MIN_RELIABLE_SAMPLE))
        scores_float = [float(x) for x in scores]
        stats = compute_statistics(scores_float)

        assert stats is not None
        assert stats.is_reliable is True

    def test_is_reliable_false_when_n_lt_5(self):
        """is_reliable should be False when sample_size < MIN_RELIABLE_SAMPLE."""
        scores = [1.0, 2.0, 3.0, 4.0]  # n=4 < 5
        stats = compute_statistics(scores)

        assert stats is not None
        assert stats.is_reliable is False

    def test_ci_narrows_with_larger_sample(self):
        """Confidence interval should narrow as sample size increases."""
        small_scores = [10.0, 20.0, 30.0, 40.0, 50.0]
        large_scores = small_scores * 10  # 50 scores with same distribution

        stats_small = compute_statistics(small_scores)
        stats_large = compute_statistics(large_scores)

        assert stats_small is not None
        assert stats_large is not None

        ci_width_small = stats_small.ci_upper - stats_small.ci_lower
        ci_width_large = stats_large.ci_upper - stats_large.ci_lower

        assert ci_width_large < ci_width_small

    def test_percentiles_with_even_count(self):
        """Percentiles should interpolate correctly with even-count data."""
        scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        stats = compute_statistics(scores)

        assert stats is not None
        assert stats.percentile_25 == pytest.approx(2.25, abs=0.01)
        assert stats.percentile_75 == pytest.approx(4.75, abs=0.01)

    def test_outlier_count_in_stats(self):
        """Outlier count should reflect actual outliers in the data."""
        # [1,2,3,4,5,100] - 100 is an outlier
        scores = [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]
        stats = compute_statistics(scores)

        assert stats is not None
        assert stats.outlier_count >= 1

    def test_confidence_level_stored(self):
        """Custom confidence level should be stored in result."""
        stats = compute_statistics([1.0, 2.0, 3.0, 4.0, 5.0], confidence=0.99)
        assert stats is not None
        assert stats.confidence_level == 0.99


# ---------------------------------------------------------------------------
# detect_outliers
# ---------------------------------------------------------------------------

class TestDetectOutliers:
    """Tests for detect_outliers()."""

    def test_known_outliers(self):
        """Detect known outliers in a dataset."""
        # Normal data plus extreme values
        scores = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 100.0]
        outliers = detect_outliers(scores)

        # Index 6 (value 100.0) should be detected
        assert 6 in outliers

    def test_no_outliers_in_clean_data(self):
        """Clean evenly-spaced data should produce no outliers."""
        scores = [10.0, 11.0, 12.0, 13.0, 14.0]
        outliers = detect_outliers(scores)

        assert outliers == []

    def test_too_few_scores(self):
        """Should return empty list for fewer than 4 scores."""
        assert detect_outliers([1.0, 2.0, 3.0]) == []
        assert detect_outliers([1.0, 2.0]) == []
        assert detect_outliers([1.0]) == []
        assert detect_outliers([]) == []

    def test_uniform_data_no_outliers(self):
        """All identical values have IQR=0, so no outliers detected."""
        scores = [5.0, 5.0, 5.0, 5.0, 5.0]
        assert detect_outliers(scores) == []

    def test_both_low_and_high_outliers(self):
        """Detect outliers on both ends."""
        scores = [-100.0, 10.0, 11.0, 12.0, 13.0, 14.0, 200.0]
        outliers = detect_outliers(scores)

        assert 0 in outliers  # -100.0
        assert 6 in outliers  # 200.0

    def test_outlier_indices_match_original_order(self):
        """Indices should refer to positions in the original (unsorted) list."""
        scores = [100.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        outliers = detect_outliers(scores)

        # Index 0 (value 100.0) should be an outlier
        assert 0 in outliers


# ---------------------------------------------------------------------------
# compute_degradation
# ---------------------------------------------------------------------------

class TestComputeDegradation:
    """Tests for compute_degradation()."""

    def test_ordered_quant_levels(self):
        """Compute drops between ordered quantization levels."""
        scores_by_quant = {
            "fp16": [90.0, 92.0],
            "q8_0": [88.0, 89.0],
            "q4_k_m": [80.0, 82.0],
        }
        drops = compute_degradation(scores_by_quant)

        assert "fp16_to_q8_0" in drops
        assert "q8_0_to_q4_k_m" in drops
        # fp16 mean=91, q8_0 mean=88.5, q4_k_m mean=81 -> drops are negative
        assert drops["fp16_to_q8_0"] < 0
        assert drops["q8_0_to_q4_k_m"] < 0

    def test_missing_levels(self):
        """Should skip missing levels and compute adjacent drops."""
        scores_by_quant = {
            "fp16": [90.0],
            # q8_0 missing
            "q4_k_m": [80.0],
        }
        drops = compute_degradation(scores_by_quant)

        assert "fp16_to_q4_k_m" in drops
        assert drops["fp16_to_q4_k_m"] == -10.0

    def test_single_level_returns_empty(self):
        """A single quant level can't produce any drops."""
        drops = compute_degradation({"fp16": [90.0]})
        assert drops == {}

    def test_empty_input(self):
        """Empty dict returns empty drops."""
        assert compute_degradation({}) == {}

    def test_empty_score_lists(self):
        """Quant levels with empty score lists should be ignored."""
        drops = compute_degradation({"fp16": [], "q8_0": []})
        assert drops == {}

    def test_unknown_quant_keys(self):
        """Non-standard quant keys should still be included."""
        scores_by_quant = {
            "fp16": [90.0],
            "custom_quant": [85.0],
        }
        drops = compute_degradation(scores_by_quant)

        # fp16 is in QUANT_ORDER, custom_quant goes at the end
        assert "fp16_to_custom_quant" in drops
        assert drops["fp16_to_custom_quant"] == -5.0

    def test_degradation_values_are_rounded(self):
        """Drop values should be rounded to 2 decimal places."""
        scores_by_quant = {
            "fp16": [90.333],
            "q8_0": [88.666],
        }
        drops = compute_degradation(scores_by_quant)
        # 88.666 - 90.333 = -1.667 -> rounded to -1.67
        assert drops["fp16_to_q8_0"] == pytest.approx(-1.67, abs=0.01)


# ---------------------------------------------------------------------------
# _percentile edge cases
# ---------------------------------------------------------------------------

class TestPercentile:
    """Tests for _percentile()."""

    def test_empty_list(self):
        """Empty list returns 0.0."""
        assert _percentile([], 50) == 0.0

    def test_single_element(self):
        """Single element returns that element for any percentile."""
        assert _percentile([42.0], 0) == 42.0
        assert _percentile([42.0], 50) == 42.0
        assert _percentile([42.0], 100) == 42.0

    def test_median_odd_count(self):
        """Median of odd-count list is the middle element."""
        assert _percentile([1.0, 2.0, 3.0], 50) == 2.0

    def test_median_even_count(self):
        """Median of even-count list is interpolated."""
        result = _percentile([1.0, 2.0, 3.0, 4.0], 50)
        assert result == pytest.approx(2.5, abs=0.01)

    def test_0th_percentile(self):
        """0th percentile is the minimum."""
        assert _percentile([1.0, 2.0, 3.0], 0) == 1.0

    def test_100th_percentile(self):
        """100th percentile is the maximum."""
        assert _percentile([1.0, 2.0, 3.0], 100) == 3.0

    def test_25th_percentile(self):
        """25th percentile of [1,2,3,4,5] = 2.0."""
        assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 25) == 2.0

    def test_75th_percentile(self):
        """75th percentile of [1,2,3,4,5] = 4.0."""
        assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 75) == 4.0

    def test_interpolation(self):
        """Percentile interpolates between adjacent values."""
        # 10th percentile of [0, 10, 20, 30]: k = 3 * 0.1 = 0.3
        # floor=0, ceil=1, result = 0*(1-0.3) + 10*0.3 = 3.0
        result = _percentile([0.0, 10.0, 20.0, 30.0], 10)
        assert result == pytest.approx(3.0, abs=0.01)


# ---------------------------------------------------------------------------
# _t_critical
# ---------------------------------------------------------------------------

class TestTCritical:
    """Tests for _t_critical()."""

    def test_known_df_values(self):
        """Exact table lookups should return the known value."""
        assert _t_critical(1) == pytest.approx(12.706, abs=0.001)
        assert _t_critical(10) == pytest.approx(2.228, abs=0.001)
        assert _t_critical(30) == pytest.approx(2.042, abs=0.001)

    def test_large_df_approaches_normal(self):
        """For very large df, t-critical should approach 1.96 (normal approximation)."""
        val = _t_critical(10000)
        assert val == pytest.approx(1.96, abs=0.05)

    def test_interpolation_between_table_entries(self):
        """df values between table entries should produce interpolated results."""
        val = _t_critical(15)  # In table, should be 2.131
        assert val == pytest.approx(2.131, abs=0.001)

        # df=35 is between 30 (2.042) and 40 (2.021)
        val_35 = _t_critical(35)
        assert 2.021 < val_35 < 2.042

    def test_df_range_1_to_100_reasonable(self):
        """All values from df=1 to df=100 should be > 1.5 and decreasing."""
        prev = float('inf')
        for df in range(1, 101):
            val = _t_critical(df)
            assert val > 1.5, f"t-critical for df={df} too low: {val}"
            assert val <= prev, f"t-critical not monotonically decreasing at df={df}"
            prev = val

    def test_df_below_table_minimum(self):
        """df < 1 should return the value for df=1 (maximum in table)."""
        # df=1 is the smallest in the table
        val = _t_critical(1)
        assert val == pytest.approx(12.706, abs=0.001)


# ---------------------------------------------------------------------------
# Integration / edge cases
# ---------------------------------------------------------------------------

class TestIntegration:
    """Integration-level tests combining multiple components."""

    def test_large_dataset_performance(self):
        """Verify it handles a large dataset without error."""
        scores = [float(i) for i in range(1000)]
        stats = compute_statistics(scores)

        assert stats is not None
        assert stats.sample_size == 1000
        assert stats.is_reliable is True
        assert stats.mean == pytest.approx(499.5, abs=0.1)

    def test_negative_scores(self):
        """Negative values should be handled correctly."""
        scores = [-10.0, -5.0, 0.0, 5.0, 10.0]
        stats = compute_statistics(scores)

        assert stats is not None
        assert stats.mean == 0.0
        assert stats.median == 0.0

    def test_float_precision(self):
        """Very close float values should produce stable results."""
        scores = [1.0000001, 1.0000002, 1.0000003, 1.0000004, 1.0000005]
        stats = compute_statistics(scores)

        assert stats is not None
        assert stats.mean == pytest.approx(1.0, abs=0.001)

    def test_statistics_dataclass_fields(self):
        """Ensure all fields of ScoreStatistics are present and typed correctly."""
        stats = compute_statistics([1.0, 2.0, 3.0, 4.0, 5.0])
        assert stats is not None

        assert isinstance(stats.mean, float)
        assert isinstance(stats.median, float)
        assert isinstance(stats.std_dev, float)
        assert isinstance(stats.ci_lower, float)
        assert isinstance(stats.ci_upper, float)
        assert isinstance(stats.confidence_level, float)
        assert isinstance(stats.sample_size, int)
        assert isinstance(stats.min_score, float)
        assert isinstance(stats.max_score, float)
        assert isinstance(stats.percentile_25, float)
        assert isinstance(stats.percentile_75, float)
        assert isinstance(stats.iqr, float)
        assert isinstance(stats.outlier_count, int)
        assert isinstance(stats.is_reliable, bool)
