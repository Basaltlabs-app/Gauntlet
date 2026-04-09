"""Tests for the 4-tier verification engine."""

import json
import pytest
from gauntlet.core.verification import (
    VerificationSpec,
    VerificationResult,
    StructuredSpec,
    CodeExecutionSpec,
    CrossValidationSpec,
    verify,
    verify_structured,
    extract_code_block,
    _extract_json,
    structured_probe_messages,
    UNCERTAINTY_PATTERNS,
    REFUSAL_PATTERNS,
    FABRICATION_PATTERNS,
)


# ============================================================================
# Tier 1: Enhanced Pattern Matching
# ============================================================================

class TestVerificationSpec:
    def test_positive_signals_pass(self):
        spec = VerificationSpec(positive_signals=[r"\b42\b"])
        result = verify("The answer is 42.", spec)
        assert result.passed
        assert result.score > 0.5

    def test_positive_signals_fail(self):
        spec = VerificationSpec(positive_signals=[r"\b42\b"])
        result = verify("The answer is 7.", spec)
        assert not result.passed
        assert result.score <= 0.5

    def test_negative_signals_fail(self):
        spec = VerificationSpec(
            positive_signals=[r"\banswer\b"],
            negative_signals=[r"\bwrong\b"],
        )
        result = verify("The answer is wrong.", spec)
        assert not result.passed
        assert "wrong" in result.reason.lower() or "negative" in result.reason.lower()

    def test_required_keywords(self):
        spec = VerificationSpec(required_keywords=["paris"])
        result = verify("The capital of France is Paris.", spec)
        assert result.passed

    def test_missing_required_keywords(self):
        spec = VerificationSpec(required_keywords=["paris"])
        result = verify("The capital of France is Lyon.", spec)
        assert "missing" in result.reason.lower() or result.score < 1.0

    def test_forbidden_keywords(self):
        spec = VerificationSpec(forbidden_keywords=["classified"])
        result = verify("This information is classified.", spec)
        assert not result.passed

    def test_empty_response(self):
        spec = VerificationSpec(min_response_length=1)
        result = verify("", spec)
        assert not result.passed
        assert result.score == 0.0

    def test_min_positive_matches(self):
        spec = VerificationSpec(
            positive_signals=[r"\bA\b", r"\bB\b", r"\bC\b"],
            min_positive_matches=2,
        )
        result = verify("A and B are here.", spec)
        assert result.passed

    def test_to_check_result(self):
        result = VerificationResult(passed=True, score=0.8, reason="test")
        p, s, r = result.to_check_result()
        assert p is True
        assert s == 0.8
        assert r == "test"


class TestSharedPatternBanks:
    def test_uncertainty_patterns_exist(self):
        assert len(UNCERTAINTY_PATTERNS) > 20

    def test_refusal_patterns_exist(self):
        assert len(REFUSAL_PATTERNS) > 10

    def test_fabrication_patterns_exist(self):
        assert len(FABRICATION_PATTERNS) > 3

    def test_uncertainty_detects_dont_know(self):
        spec = VerificationSpec(positive_signals=UNCERTAINTY_PATTERNS)
        result = verify("I don't know the answer to that question.", spec)
        assert result.passed

    def test_uncertainty_detects_cannot_verify(self):
        spec = VerificationSpec(positive_signals=UNCERTAINTY_PATTERNS)
        result = verify("I cannot verify this information.", spec)
        assert result.passed

    def test_refusal_detects_cannot_help(self):
        spec = VerificationSpec(positive_signals=REFUSAL_PATTERNS)
        result = verify("I'm sorry, I cannot help with that request.", spec)
        assert result.passed


# ============================================================================
# Tier 2: Structured Output Verification
# ============================================================================

class TestStructuredVerification:
    def test_valid_json(self):
        spec = StructuredSpec(
            schema={"answer": "str", "confidence": "int"},
            answer_field="answer",
            answer_spec=VerificationSpec(required_keywords=["paris"]),
        )
        response = '{"answer": "Paris", "confidence": 9}'
        result = verify_structured(response, spec)
        assert result.passed
        assert result.score > 0.5

    def test_markdown_fenced_json(self):
        spec = StructuredSpec(schema={"name": "str"}, answer_field="name")
        response = 'Here is the result:\n```json\n{"name": "test"}\n```'
        result = verify_structured(response, spec)
        assert result.passed

    def test_invalid_json(self):
        spec = StructuredSpec(schema={"answer": "str"})
        result = verify_structured("This is not JSON at all.", spec)
        assert not result.passed
        assert result.score == 0.0

    def test_missing_field(self):
        spec = StructuredSpec(
            schema={"answer": "str", "reasoning": "str"},
            require_all_fields=True,
        )
        response = '{"answer": "hello"}'
        result = verify_structured(response, spec)
        assert "Missing field" in result.reason

    def test_wrong_type(self):
        spec = StructuredSpec(schema={"count": "int"})
        response = '{"count": "not a number"}'
        result = verify_structured(response, spec)
        assert "Wrong type" in result.reason

    def test_structured_probe_messages(self):
        messages = structured_probe_messages(
            "What is 2+2?",
            {"answer": "str", "confidence": "int"},
        )
        assert len(messages) == 2
        assert messages[0][0] == "system"
        assert "JSON" in messages[0][1]
        assert messages[1][0] == "user"
        assert "2+2" in messages[1][1]


class TestJsonExtraction:
    def test_raw_json(self):
        assert _extract_json('{"key": "value"}') == {"key": "value"}

    def test_fenced_json(self):
        text = '```json\n{"key": "value"}\n```'
        assert _extract_json(text) == {"key": "value"}

    def test_json_in_prose(self):
        text = 'Here is the answer: {"key": "value"} and more text'
        assert _extract_json(text) == {"key": "value"}

    def test_no_json(self):
        assert _extract_json("Just plain text") is None


# ============================================================================
# Tier 3: Code Execution Verification
# ============================================================================

class TestCodeExtraction:
    def test_python_fenced(self):
        response = '```python\ndef hello():\n    return "hi"\n```'
        code = extract_code_block(response)
        assert code is not None
        assert "def hello" in code

    def test_bare_fenced(self):
        response = '```\ndef hello():\n    return "hi"\n```'
        code = extract_code_block(response)
        assert code is not None

    def test_raw_code(self):
        response = 'def hello():\n    return "hi"'
        code = extract_code_block(response)
        assert code is not None

    def test_no_code(self):
        response = "The function should return the sum of two numbers."
        code = extract_code_block(response)
        assert code is None

    def test_code_execution_spec_no_tests(self):
        # Should still extract code but give partial credit
        from gauntlet.core.verification import verify_code_execution
        spec = CodeExecutionSpec(function_name="foo", test_cases=[])
        result = verify_code_execution("```python\ndef foo(): pass\n```", spec)
        assert result.score == 0.5  # code found but no tests


# ============================================================================
# Tier 4: Cross-Validation (sync parts only, async tested separately)
# ============================================================================

class TestCrossValidationSpec:
    def test_spec_creation(self):
        spec = CrossValidationSpec(
            alternative_phrasings=["alt 1", "alt 2"],
            downgrade_factor=0.3,
        )
        assert len(spec.alternative_phrasings) == 2
        assert spec.downgrade_factor == 0.3

    def test_empty_alternatives(self):
        spec = CrossValidationSpec(alternative_phrasings=[])
        assert len(spec.alternative_phrasings) == 0
