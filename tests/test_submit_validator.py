"""Tests for the shared submission validator.

The MCP write path used to skip every check that /api/submit enforces.
This validator is the shared backstop used by both paths.
"""

from __future__ import annotations

import time

import pytest

from gauntlet.mcp.submit_validator import (
    validate_submission,
    SCORE_CONSISTENCY_DELTA,
)


def _good_payload(**overrides) -> dict:
    """A baseline payload that passes every check."""
    payload = {
        "model_name": "qwen2.5:14b",
        "overall_score": 82.0,
        "category_scores": {"REASONING": 84.0, "SAFETY": 80.0, "CONTEXT": 79.0},
        "total_probes": 80,
        "hardware": {"cpu_arch": "arm64", "gpu_class": "apple_silicon", "ram_total_gb": 16},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_baseline_payload_validates(monkeypatch):
    # Use unique name so dedup window doesn't trip on parallel test runs
    monkeypatch.setattr(
        "gauntlet.mcp.submit_validator._recent_dedup", {}, raising=False
    )
    err = validate_submission(_good_payload(), check_dedup=False)
    assert err is None


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

def test_missing_model_name_rejected():
    p = _good_payload()
    del p["model_name"]
    err = validate_submission(p, check_dedup=False)
    assert err and "model_name" in err


def test_missing_overall_score_rejected():
    p = _good_payload()
    del p["overall_score"]
    err = validate_submission(p, check_dedup=False)
    assert err and "overall_score" in err


# ---------------------------------------------------------------------------
# Range checks
# ---------------------------------------------------------------------------

def test_negative_score_rejected():
    err = validate_submission(_good_payload(overall_score=-5), check_dedup=False)
    assert err and "out of range" in err


def test_score_above_100_rejected():
    err = validate_submission(_good_payload(overall_score=150), check_dedup=False)
    assert err and "out of range" in err


def test_score_must_be_numeric():
    err = validate_submission(_good_payload(overall_score="high"), check_dedup=False)
    assert err and "number" in err


def test_short_model_name_rejected():
    err = validate_submission(_good_payload(model_name="x"), check_dedup=False)
    assert err and "model_name length" in err


def test_long_model_name_rejected():
    err = validate_submission(_good_payload(model_name="x" * 200), check_dedup=False)
    assert err and "model_name length" in err


# ---------------------------------------------------------------------------
# Category scores
# ---------------------------------------------------------------------------

def test_missing_categories_rejected():
    err = validate_submission(_good_payload(category_scores={}), check_dedup=False)
    assert err and "Insufficient category data" in err


def test_one_category_rejected():
    err = validate_submission(
        _good_payload(category_scores={"only": 80.0}), check_dedup=False
    )
    assert err and "Insufficient category data" in err


def test_unknown_category_rejected_when_allowlist_provided():
    err = validate_submission(
        _good_payload(category_scores={"REASONING": 80, "FAKE_CATEGORY": 80, "SAFETY": 80}),
        valid_categories={"REASONING", "SAFETY", "CONTEXT"},
        check_dedup=False,
    )
    assert err and "Unknown categories" in err and "FAKE_CATEGORY" in err


def test_unknown_category_accepted_when_no_allowlist():
    """Without an allowlist the validator can't know — caller's choice."""
    err = validate_submission(
        _good_payload(category_scores={"FOO": 80, "BAR": 80}),
        valid_categories=None,
        check_dedup=False,
    )
    # FOO/BAR are accepted as categories, but score consistency may still fire
    # depending on overall_score. With overall=82 and avg=80, delta=2 → OK.
    assert err is None


def test_underscore_prefixed_keys_dont_count_toward_minimum():
    """`_perplexity_raw` is a synthetic key, not a real category."""
    err = validate_submission(
        _good_payload(category_scores={"_perplexity_raw": 5.0, "REASONING": 80}),
        check_dedup=False,
    )
    assert err and "Insufficient category data" in err


# ---------------------------------------------------------------------------
# Score consistency
# ---------------------------------------------------------------------------

def test_score_consistency_within_tolerance_passes():
    err = validate_submission(
        _good_payload(
            overall_score=85.0,
            category_scores={"REASONING": 90, "SAFETY": 85, "CONTEXT": 80},  # avg=85
        ),
        check_dedup=False,
    )
    assert err is None


def test_score_inconsistency_rejected():
    """Overall 95 vs cat avg 50 → delta 45 > 40 tolerance."""
    err = validate_submission(
        _good_payload(
            overall_score=95.0,
            category_scores={"REASONING": 50, "SAFETY": 50, "CONTEXT": 50},
        ),
        check_dedup=False,
    )
    assert err and "Score inconsistency" in err


# ---------------------------------------------------------------------------
# Probe count
# ---------------------------------------------------------------------------

def test_too_few_probes_rejected():
    err = validate_submission(_good_payload(total_probes=2), check_dedup=False)
    assert err and "total_probes" in err


def test_probe_count_must_be_int():
    err = validate_submission(_good_payload(total_probes="lots"), check_dedup=False)
    assert err and "total_probes" in err


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------

def test_attestation_must_be_dict_when_present():
    err = validate_submission(
        _good_payload(attestation="not a dict"), check_dedup=False
    )
    assert err and "attestation" in err


def test_attestation_missing_version_rejected():
    err = validate_submission(
        _good_payload(attestation={"hardware_tier": "CONSUMER_HIGH"}),
        check_dedup=False,
    )
    assert err and "gauntlet_version" in err


def test_attestation_invalid_tier_rejected():
    err = validate_submission(
        _good_payload(attestation={
            "gauntlet_version": "2.1.2",
            "hardware_tier": "INVENTED_TIER",
        }),
        valid_hardware_tiers={"CLOUD", "CONSUMER_HIGH", "CONSUMER_MID"},
        check_dedup=False,
    )
    assert err and "Invalid attestation hardware_tier" in err


def test_attestation_omitted_is_fine():
    err = validate_submission(_good_payload(), check_dedup=False)
    assert err is None


# ---------------------------------------------------------------------------
# probe_details size cap
# ---------------------------------------------------------------------------

def test_probe_details_too_many_modules_rejected():
    pd = {f"module_{i}": [] for i in range(35)}
    err = validate_submission(_good_payload(probe_details=pd), check_dedup=False)
    assert err and "probe_details" in err


def test_probe_details_too_many_probes_rejected():
    pd = {"REASONING": [{"id": str(i)} for i in range(250)]}
    err = validate_submission(_good_payload(probe_details=pd), check_dedup=False)
    assert err and "probe_details" in err


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def test_duplicate_submission_rejected():
    p = _good_payload()
    # First passes, second within window is rejected
    assert validate_submission(p, check_dedup=True) is None
    err = validate_submission(p, check_dedup=True)
    assert err and "Duplicate" in err


def test_dedup_can_be_disabled():
    p = _good_payload(model_name="dedup-disabled-test")
    assert validate_submission(p, check_dedup=False) is None
    # Even immediate retry passes when dedup is off
    assert validate_submission(p, check_dedup=False) is None


def test_different_score_is_not_duplicate():
    a = _good_payload(model_name="diff-score-test", overall_score=80,
                      category_scores={"REASONING": 80, "SAFETY": 80, "CONTEXT": 80})
    b = _good_payload(model_name="diff-score-test", overall_score=82,
                      category_scores={"REASONING": 82, "SAFETY": 82, "CONTEXT": 82})
    assert validate_submission(a, check_dedup=True) is None
    assert validate_submission(b, check_dedup=True) is None  # different score → not dup
