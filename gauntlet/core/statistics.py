"""Statistical analysis for Gauntlet community data.

Uses scipy.stats when available (install via `pip install gauntlet-cli[stats]`).
Falls back to pure-Python approximations for basic installs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# Try to import scipy for precise CI computation
try:
    from scipy import stats as scipy_stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# Precomputed t-distribution critical values for 95% CI (two-tailed)
# Keys are degrees of freedom (n-1), values are t-critical
_T_TABLE_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    25: 2.060, 30: 2.042, 40: 2.021, 50: 2.009, 60: 2.000,
    80: 1.990, 100: 1.984, 200: 1.972, 500: 1.965,
}


def _t_critical(df: int, confidence: float = 0.95) -> float:
    """Get t-critical value for given degrees of freedom and confidence level."""
    if HAS_SCIPY:
        alpha = 1 - confidence
        return scipy_stats.t.ppf(1 - alpha / 2, df)

    # Fallback: lookup table only supports 95% CI
    if confidence != 0.95:
        import warnings
        warnings.warn(
            f"Pure-Python CI only supports 95% confidence; using 95% instead of {confidence:.0%}. "
            "Install scipy for arbitrary confidence levels: pip install gauntlet-cli[stats]",
            stacklevel=3,
        )
        confidence = 0.95  # noqa: F841 — corrects value for caller awareness

    if df in _T_TABLE_95:
        return _T_TABLE_95[df]

    # Interpolate between nearest keys
    keys = sorted(_T_TABLE_95.keys())
    if df < keys[0]:
        return _T_TABLE_95[keys[0]]
    if df > keys[-1]:
        return 1.96  # Normal approximation for large df

    # Find surrounding keys
    for i in range(len(keys) - 1):
        if keys[i] <= df <= keys[i + 1]:
            low_df, high_df = keys[i], keys[i + 1]
            low_t, high_t = _T_TABLE_95[low_df], _T_TABLE_95[high_df]
            # Linear interpolation
            frac = (df - low_df) / (high_df - low_df)
            return low_t + frac * (high_t - low_t)

    return 1.96  # Fallback


@dataclass
class ScoreStatistics:
    """Statistical summary of a set of scores."""
    mean: float
    median: float
    std_dev: float
    ci_lower: float          # Confidence interval lower bound
    ci_upper: float          # Confidence interval upper bound
    confidence_level: float  # Usually 0.95
    sample_size: int
    min_score: float
    max_score: float
    percentile_25: float
    percentile_75: float
    iqr: float               # Interquartile range
    outlier_count: int       # Scores outside 1.5*IQR from Q1/Q3
    is_reliable: bool        # sample_size >= MIN_RELIABLE_SAMPLE


# Minimum sample size for reliable statistics
MIN_RELIABLE_SAMPLE = 5


def _percentile(sorted_data: list[float], p: float) -> float:
    """Compute percentile using linear interpolation."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    k = (n - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def compute_statistics(
    scores: list[float],
    confidence: float = 0.95,
) -> Optional[ScoreStatistics]:
    """Compute statistical summary of a list of scores.

    Returns None if fewer than 2 scores provided.
    """
    if len(scores) < 2:
        if len(scores) == 1:
            return ScoreStatistics(
                mean=scores[0], median=scores[0], std_dev=0.0,
                ci_lower=scores[0], ci_upper=scores[0],
                confidence_level=confidence, sample_size=1,
                min_score=scores[0], max_score=scores[0],
                percentile_25=scores[0], percentile_75=scores[0],
                iqr=0.0, outlier_count=0, is_reliable=False,
            )
        return None

    n = len(scores)
    sorted_scores = sorted(scores)

    # Central tendency
    mean = sum(scores) / n
    median = _percentile(sorted_scores, 50)

    # Spread
    variance = sum((x - mean) ** 2 for x in scores) / (n - 1)  # sample variance
    std_dev = math.sqrt(variance)

    # Confidence interval
    # In pure-Python mode, only 95% CI is supported (_t_critical warns and uses 95%)
    effective_confidence = confidence if HAS_SCIPY else 0.95
    se = std_dev / math.sqrt(n)
    t_crit = _t_critical(n - 1, confidence)
    margin = t_crit * se
    ci_lower = mean - margin
    ci_upper = mean + margin

    # Percentiles
    q1 = _percentile(sorted_scores, 25)
    q3 = _percentile(sorted_scores, 75)
    iqr = q3 - q1

    # Outlier detection (1.5 * IQR rule)
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    outlier_count = sum(1 for x in scores if x < lower_fence or x > upper_fence)

    return ScoreStatistics(
        mean=round(mean, 2),
        median=round(median, 2),
        std_dev=round(std_dev, 2),
        ci_lower=round(ci_lower, 2),
        ci_upper=round(ci_upper, 2),
        confidence_level=effective_confidence,
        sample_size=n,
        min_score=round(min(scores), 2),
        max_score=round(max(scores), 2),
        percentile_25=round(q1, 2),
        percentile_75=round(q3, 2),
        iqr=round(iqr, 2),
        outlier_count=outlier_count,
        is_reliable=n >= MIN_RELIABLE_SAMPLE,
    )


def detect_outliers(scores: list[float]) -> list[int]:
    """Return indices of outlier scores using 1.5*IQR method."""
    if len(scores) < 4:
        return []

    sorted_scores = sorted(scores)
    q1 = _percentile(sorted_scores, 25)
    q3 = _percentile(sorted_scores, 75)
    iqr = q3 - q1

    if iqr == 0:
        return []

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    return [i for i, x in enumerate(scores) if x < lower or x > upper]


def compute_degradation(
    scores_by_quant: dict[str, list[float]],
) -> dict[str, float]:
    """Compute score degradation across quantization levels.

    Input: {"fp16": [scores], "q8_0": [scores], "q4_k_m": [scores]}
    Output: {"fp16_to_q8_0": -2.3, "q8_0_to_q4_k_m": -5.1}
    """
    # Canonical ordering of quantization levels (highest to lowest precision)
    QUANT_ORDER = [
        "fp16", "fp32", "q8_0", "q6_k", "q5_k_m", "q5_0",
        "q4_k_m", "q4_0", "q3_k_m", "q2_k",
    ]

    # Filter to levels that have data and compute means
    available = {}
    for quant in QUANT_ORDER:
        if quant in scores_by_quant and scores_by_quant[quant]:
            available[quant] = sum(scores_by_quant[quant]) / len(scores_by_quant[quant])

    # Also check for keys not in QUANT_ORDER
    for quant, scores in scores_by_quant.items():
        if quant not in available and scores:
            available[quant] = sum(scores) / len(scores)

    if len(available) < 2:
        return {}

    # Compute pairwise drops between adjacent available levels
    ordered_keys = [q for q in QUANT_ORDER if q in available]
    # Add any extra keys at the end
    for k in available:
        if k not in ordered_keys:
            ordered_keys.append(k)

    drops = {}
    for i in range(len(ordered_keys) - 1):
        higher = ordered_keys[i]
        lower = ordered_keys[i + 1]
        drop = available[lower] - available[higher]
        drops[f"{higher}_to_{lower}"] = round(drop, 2)

    return drops
