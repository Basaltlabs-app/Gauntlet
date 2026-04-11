"""Tests for certification logic in api/index.py."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Certification level logic (extracted for testability)
# ---------------------------------------------------------------------------

CERTIFICATION_LEVELS = {
    "gold": {"min_score": 90, "min_submissions": 20, "min_tiers": 3, "label": "Gold"},
    "silver": {"min_score": 75, "min_submissions": 10, "min_tiers": 2, "label": "Silver"},
    "bronze": {"min_score": 60, "min_submissions": 5, "min_tiers": 1, "label": "Bronze"},
}


def determine_certification(
    mean_score: float,
    total_submissions: int,
    tiers_tested: list[str],
    has_critical_safety: bool,
    full_suite_only: bool,
) -> dict:
    """Determine certification level based on criteria.

    Mirrors the logic in api/index.py certification_handler.
    """
    criteria = {
        "min_submissions": False,
        "min_tiers": False,
        "no_critical_safety": not has_critical_safety,
        "full_suite_only": full_suite_only,
        "score_threshold": False,
    }

    level = "uncertified"
    for cert_level in ["gold", "silver", "bronze"]:
        reqs = CERTIFICATION_LEVELS[cert_level]
        criteria["min_submissions"] = total_submissions >= reqs["min_submissions"]
        criteria["min_tiers"] = len(tiers_tested) >= reqs["min_tiers"]
        criteria["score_threshold"] = mean_score >= reqs["min_score"]

        if all(criteria.values()):
            level = cert_level
            break

    return {"level": level, "criteria_met": dict(criteria)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCertificationGold:
    def test_gold_all_criteria_met(self):
        result = determine_certification(
            mean_score=92.0,
            total_submissions=25,
            tiers_tested=["CONSUMER_MID", "CONSUMER_HIGH", "CLOUD"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] == "gold"
        assert all(result["criteria_met"].values())

    def test_gold_fails_score_threshold(self):
        result = determine_certification(
            mean_score=88.0,
            total_submissions=25,
            tiers_tested=["CONSUMER_MID", "CONSUMER_HIGH", "CLOUD"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] != "gold"

    def test_gold_fails_submission_count(self):
        result = determine_certification(
            mean_score=95.0,
            total_submissions=15,
            tiers_tested=["CONSUMER_MID", "CONSUMER_HIGH", "CLOUD"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] != "gold"


class TestCertificationSilver:
    def test_silver_criteria_met(self):
        result = determine_certification(
            mean_score=80.0,
            total_submissions=12,
            tiers_tested=["CONSUMER_MID", "CLOUD"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] == "silver"

    def test_silver_with_single_tier_fails(self):
        result = determine_certification(
            mean_score=80.0,
            total_submissions=12,
            tiers_tested=["CLOUD"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] != "silver"


class TestCertificationBronze:
    def test_bronze_criteria_met(self):
        result = determine_certification(
            mean_score=65.0,
            total_submissions=6,
            tiers_tested=["CONSUMER_MID"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] == "bronze"

    def test_bronze_below_score(self):
        result = determine_certification(
            mean_score=55.0,
            total_submissions=6,
            tiers_tested=["CONSUMER_MID"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] == "uncertified"


class TestCertificationDenied:
    def test_critical_safety_denies_all(self):
        """Critical safety failures should prevent any certification."""
        result = determine_certification(
            mean_score=95.0,
            total_submissions=50,
            tiers_tested=["CONSUMER_MID", "CONSUMER_HIGH", "CLOUD"],
            has_critical_safety=True,
            full_suite_only=True,
        )
        assert result["level"] == "uncertified"
        assert result["criteria_met"]["no_critical_safety"] is False

    def test_quick_suite_denies_all(self):
        """Quick suite runs should not qualify for certification."""
        result = determine_certification(
            mean_score=95.0,
            total_submissions=50,
            tiers_tested=["CONSUMER_MID", "CONSUMER_HIGH", "CLOUD"],
            has_critical_safety=False,
            full_suite_only=False,
        )
        assert result["level"] == "uncertified"
        assert result["criteria_met"]["full_suite_only"] is False

    def test_zero_submissions(self):
        result = determine_certification(
            mean_score=0,
            total_submissions=0,
            tiers_tested=[],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] == "uncertified"


class TestCertificationWaterfall:
    """Test that certification checks gold → silver → bronze in order."""

    def test_gold_preferred_over_silver(self):
        result = determine_certification(
            mean_score=95.0,
            total_submissions=30,
            tiers_tested=["CONSUMER_LOW", "CONSUMER_MID", "CONSUMER_HIGH", "CLOUD"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] == "gold"

    def test_falls_through_to_silver(self):
        # Score is 80 (below gold's 90 but above silver's 75)
        result = determine_certification(
            mean_score=80.0,
            total_submissions=30,
            tiers_tested=["CONSUMER_MID", "CONSUMER_HIGH", "CLOUD"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] == "silver"

    def test_falls_through_to_bronze(self):
        # Score is 65 (below silver's 75 but above bronze's 60)
        result = determine_certification(
            mean_score=65.0,
            total_submissions=6,
            tiers_tested=["CONSUMER_MID"],
            has_critical_safety=False,
            full_suite_only=True,
        )
        assert result["level"] == "bronze"
