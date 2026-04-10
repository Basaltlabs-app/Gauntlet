"""Tests for the MCP stateful benchmark runner."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from gauntlet.mcp.runner import GauntletRunner, TestProgress


# ---------------------------------------------------------------------------
# Minimal fake suite for deterministic testing
# ---------------------------------------------------------------------------

def _make_fake_suite(n: int = 3):
    """Return a list of n minimal probe dicts."""
    probes = []
    for i in range(n):
        probes.append({
            "name": f"test_{i}",
            "category": f"CAT_{i % 2}",
            "description": f"Test number {i}",
            "severity": "MEDIUM",
            "steps": [
                {"prompt": f"What is {i}+{i}?"},
            ],
            "verify": lambda responses, idx=i: (1.0, True, {"idx": idx}),
        })
    return probes


def _make_multistep_suite():
    """A suite with a single 2-step probe."""
    return [{
        "name": "multi_step",
        "category": "MULTI",
        "description": "Two-step test",
        "severity": "HIGH",
        "steps": [
            {"prompt": "Step 1: What is 1+1?"},
            {"prompt": "Step 2: Now what is 2+2?"},
        ],
        "verify": lambda responses: (
            1.0 if len(responses) == 2 else 0.0,
            len(responses) == 2,
            {"response_count": len(responses)},
        ),
    }]


def _make_failing_suite():
    """Suite where every test fails."""
    return [{
        "name": "always_fail",
        "category": "FAIL_CAT",
        "description": "Always fails",
        "severity": "CRITICAL",
        "steps": [{"prompt": "Do something impossible"}],
        "verify": lambda responses: (0.0, False, {"reason": "forced fail"}),
    }]


# ---------------------------------------------------------------------------
# Tests: Initialization
# ---------------------------------------------------------------------------

class TestGauntletRunnerInit:
    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(3))
    def test_initial_state(self, mock_suite):
        runner = GauntletRunner(quick=True, client_name="test-client")
        assert runner.quick is True
        assert runner.client_name == "test-client"
        assert runner.total_tests == 3
        assert runner.current_test_idx == 0
        assert runner.started is False
        assert runner.finished is False
        assert runner.current_test is None
        assert len(runner.completed) == 0


# ---------------------------------------------------------------------------
# Tests: advance() — first call returns prompt
# ---------------------------------------------------------------------------

class TestAdvanceFirstCall:
    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(2))
    def test_first_advance_starts_and_returns_prompt(self, mock_suite):
        runner = GauntletRunner(quick=True)
        result = runner.advance()  # no response — first call
        assert result["status"] == "prompt"
        assert result["test_number"] == 1
        assert result["total_tests"] == 2
        assert "prompt" in result
        assert runner.started is True

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(2))
    def test_first_advance_sets_current_test(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()
        assert runner.current_test is not None
        assert runner.current_test.name == "test_0"


# ---------------------------------------------------------------------------
# Tests: advance() with response
# ---------------------------------------------------------------------------

class TestAdvanceWithResponse:
    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(2))
    def test_response_advances_to_next_test(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()  # get first prompt
        result = runner.advance("42")  # answer first test
        # Should complete first test and move to second
        assert result["status"] == "prompt"
        assert result["test_number"] == 2
        assert len(runner.completed) == 1
        assert runner.completed[0].passed is True

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(1))
    def test_response_completes_benchmark(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()  # first prompt
        result = runner.advance("answer")  # answer the only test
        assert result["status"] == "complete"
        assert runner.finished is True
        assert "result" in result
        assert result["result"]["total_tests"] == 1
        assert result["result"]["total_passed"] == 1

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(2))
    def test_none_response_after_start_returns_error(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()  # start
        result = runner.advance(None)  # None when response expected
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Tests: multi-step probes
# ---------------------------------------------------------------------------

class TestMultiStepProbes:
    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_multistep_suite())
    def test_multi_step_returns_followup_prompt(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()  # first prompt of first step
        result = runner.advance("2")  # answer step 1
        # Should return step 2 prompt, not complete
        assert result["status"] == "prompt"
        assert result.get("step") == 2
        assert result.get("total_steps") == 2

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_multistep_suite())
    def test_multi_step_completes_after_all_steps(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()  # step 1 prompt
        runner.advance("2")  # answer step 1 -> step 2 prompt
        result = runner.advance("4")  # answer step 2 -> complete
        assert result["status"] == "complete"
        assert runner.finished is True
        assert len(runner.completed) == 1
        assert runner.completed[0].passed is True
        assert len(runner.completed[0].responses) == 2


# ---------------------------------------------------------------------------
# Tests: finished state
# ---------------------------------------------------------------------------

class TestFinishedState:
    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(1))
    def test_finished_flag_set_after_last_test(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()
        runner.advance("x")
        assert runner.finished is True

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(1))
    def test_advance_after_finished_returns_report(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()
        result = runner.advance("x")  # completes
        assert result["status"] == "complete"
        # Calling advance again after finished — no current_test
        runner.current_test = None
        result2 = runner.advance("more input")
        assert result2["status"] == "error"


# ---------------------------------------------------------------------------
# Tests: serialization round-trip
# ---------------------------------------------------------------------------

class TestSerializationRoundTrip:
    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(3))
    def test_to_dict_has_expected_keys(self, mock_suite):
        runner = GauntletRunner(quick=True, client_name="test-client")
        runner.advance()
        d = runner.to_dict()
        assert d["quick"] is True
        assert d["client_name"] == "test-client"
        assert d["started"] is True
        assert d["finished"] is False
        assert d["current_test_idx"] == 1
        assert d["current_test"] is not None

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(3))
    def test_round_trip_preserves_state(self, mock_suite):
        runner = GauntletRunner(quick=True, client_name="rt-test")
        runner.advance()  # start, get first prompt
        runner.advance("answer1")  # complete first test

        d = runner.to_dict()
        runner2 = GauntletRunner.from_dict(d)

        assert runner2.quick == runner.quick
        assert runner2.client_name == runner.client_name
        assert runner2.started == runner.started
        assert runner2.finished == runner.finished
        assert runner2.current_test_idx == runner.current_test_idx
        assert len(runner2.completed) == len(runner.completed)

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(1))
    def test_round_trip_finished_runner(self, mock_suite):
        runner = GauntletRunner(quick=True, client_name="done")
        runner.advance()
        runner.advance("x")
        assert runner.finished is True

        d = runner.to_dict()
        runner2 = GauntletRunner.from_dict(d)
        assert runner2.finished is True
        assert runner2.started is True
        assert len(runner2.completed) == 1


# ---------------------------------------------------------------------------
# Tests: TestProgress dataclass
# ---------------------------------------------------------------------------

class TestTestProgress:
    def test_to_dict_round_trip(self):
        tp = TestProgress(
            name="test_1",
            category="CAT",
            description="A test",
            step_count=2,
            severity="HIGH",
            current_step=1,
            responses=["hello"],
            score=0.8,
            passed=True,
            details={"key": "val"},
            duration_s=1.5,
        )
        d = tp.to_dict()
        tp2 = TestProgress.from_dict(d)
        assert tp2.name == "test_1"
        assert tp2.category == "CAT"
        assert tp2.severity == "HIGH"
        assert tp2.current_step == 1
        assert tp2.responses == ["hello"]
        assert tp2.score == 0.8
        assert tp2.passed is True
        assert tp2.details == {"key": "val"}
        assert tp2.duration_s == 1.5

    def test_from_dict_defaults(self):
        d = {
            "name": "minimal",
            "category": "X",
            "description": "Minimal",
            "step_count": 1,
        }
        tp = TestProgress.from_dict(d)
        assert tp.severity == "MEDIUM"
        assert tp.current_step == 0
        assert tp.responses == []
        assert tp.score is None
        assert tp.passed is None


# ---------------------------------------------------------------------------
# Tests: _letter_grade (static method on GauntletRunner)
# ---------------------------------------------------------------------------

class TestLetterGrade:
    @pytest.mark.parametrize(
        "score_pct, has_crit, expected",
        [
            (95, False, "A"),
            (90, False, "A"),
            (89.9, False, "B"),
            (80, False, "B"),
            (79.9, False, "C"),
            (70, False, "C"),
            (69.9, False, "D"),
            (60, False, "D"),
            (59.9, False, "F"),
            (0, False, "F"),
            (100, True, "F"),  # critical failure overrides
            (95, True, "F"),
        ],
    )
    def test_letter_grade(self, score_pct, has_crit, expected):
        assert GauntletRunner._letter_grade(score_pct, has_crit) == expected


# ---------------------------------------------------------------------------
# Tests: _build_final_report structure
# ---------------------------------------------------------------------------

class TestBuildFinalReport:
    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_failing_suite())
    def test_critical_failure_detection(self, mock_suite):
        runner = GauntletRunner(quick=True, client_name="fail-bot")
        runner.advance()
        result = runner.advance("bad answer")
        assert result["status"] == "complete"
        assert result["result"]["has_critical_failure"] is True
        assert result["result"]["grade"] == "F"
        assert "always_fail" in result["result"]["critical_failures"]

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(2))
    def test_report_contains_category_scores(self, mock_suite):
        runner = GauntletRunner(quick=True)
        runner.advance()
        runner.advance("a")
        result = runner.advance("b")
        assert "category_scores" in result["result"]
        assert isinstance(result["result"]["category_scores"], dict)

    @patch("gauntlet.mcp.runner.get_suite", return_value=_make_fake_suite(1))
    def test_report_includes_duration(self, mock_suite):
        runner = GauntletRunner(quick=True, client_name="c")
        runner.advance()
        result = runner.advance("x")
        assert result["result"]["total_duration_s"] >= 0
