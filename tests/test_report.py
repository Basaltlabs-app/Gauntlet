"""Tests for report generation (Finding dataclass + verdicts)."""
from gauntlet.core.report import Finding, generate_verdict, MODULE_LABELS


class TestFinding:
    def test_critical_finding(self):
        f = Finding(level="CRITICAL", summary="Complied with harmful request",
                    module_name="SAFETY_BOUNDARY", probe_id="saf_01", deduction=8.0)
        assert f.level == "CRITICAL"
        assert f.deduction == 8.0

    def test_clean_finding(self):
        f = Finding(level="CLEAN", summary="All good", module_name="SYCOPHANCY_TRAP")
        assert f.probe_id is None
        assert f.deduction == 0.0

    def test_to_dict(self):
        f = Finding(level="WARNING", summary="Test", module_name="X", deduction=1.234)
        d = f.to_dict()
        assert d["deduction"] == 1.23


class TestVerdictSingleModel:
    def test_returns_none(self):
        from gauntlet.core.trust_score import TrustScore
        ts1 = TrustScore(score=80, profile="coder")
        assert generate_verdict([("model-a", ts1)], profile="coder") is None


class TestVerdictTwoModels:
    def test_clear_winner(self):
        from gauntlet.core.trust_score import TrustScore
        ts1 = TrustScore(score=84, profile="coder")
        ts2 = TrustScore(score=62, profile="coder")
        verdict = generate_verdict([("gemma4:e2b", ts1), ("qwen3.5:4b", ts2)], profile="coder")
        assert verdict is not None
        assert "gemma4:e2b" in verdict

    def test_tie(self):
        from gauntlet.core.trust_score import TrustScore
        ts1 = TrustScore(score=80, profile="coder")
        ts2 = TrustScore(score=80, profile="coder")
        verdict = generate_verdict([("model-a", ts1), ("model-b", ts2)], profile="coder")
        assert verdict is not None
        assert "both" in verdict.lower() or "80/100" in verdict


class TestModuleLabels:
    def test_all_modules_have_labels(self):
        expected = ["AMBIGUITY_HONESTY", "SYCOPHANCY_TRAP", "INSTRUCTION_ADHERENCE",
                    "CONSISTENCY_DRIFT", "SAFETY_BOUNDARY", "HALLUCINATION_PROBE",
                    "CONTEXT_FIDELITY", "REFUSAL_CALIBRATION"]
        for mod in expected:
            assert mod in MODULE_LABELS
