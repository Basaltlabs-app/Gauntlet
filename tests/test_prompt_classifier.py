"""Tests for prompt-to-profile classifier."""
from gauntlet.core.prompt_classifier import classify_prompt


class TestCodingPrompts:
    def test_write_function(self):
        assert classify_prompt("Write a function to sort a list") == "coder"

    def test_implement_api(self):
        assert classify_prompt("Implement a REST API endpoint") == "coder"

    def test_debug_code(self):
        assert classify_prompt("Debug this Python script") == "coder"

    def test_refactor(self):
        assert classify_prompt("Refactor this class to use composition") == "coder"


class TestResearchPrompts:
    def test_explain_concept(self):
        assert classify_prompt("Explain quantum entanglement") == "researcher"

    def test_summarize(self):
        assert classify_prompt("Summarize the key findings of this paper") == "researcher"

    def test_analyze_data(self):
        assert classify_prompt("Analyze the trends in this dataset") == "researcher"

    def test_compare_theories(self):
        assert classify_prompt("Compare and contrast these two theories") == "researcher"


class TestAssistantDefault:
    def test_empty_prompt(self):
        assert classify_prompt("") == "assistant"

    def test_generic_greeting(self):
        assert classify_prompt("Hello, how are you?") == "assistant"

    def test_nonsensical(self):
        assert classify_prompt("asdkjhgf qwerty zxcv") == "assistant"

    def test_general_request(self):
        assert classify_prompt("Help me plan a birthday party") == "assistant"


class TestTieBreaking:
    def test_mixed_code_research(self):
        result = classify_prompt("explain how to implement this")
        assert result in ("coder", "researcher")


class TestCaseInsensitive:
    def test_uppercase(self):
        assert classify_prompt("WRITE A FUNCTION") == "coder"

    def test_mixed_case(self):
        assert classify_prompt("Explain The Algorithm") == "researcher"
