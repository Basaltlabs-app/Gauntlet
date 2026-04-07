"""Stateful MCP benchmark runner.

Manages the state machine for running Gauntlet probes through conversational
tool calls. Each call to `advance()` either returns the next prompt or a result.

State machine:
    idle -> started -> awaiting_response -> (verify | next_step) -> ... -> complete
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from gauntlet.mcp.probes import get_suite


@dataclass
class TestProgress:
    """Progress for a single test."""
    name: str
    category: str
    description: str
    step_count: int
    current_step: int = 0
    responses: list[str] = field(default_factory=list)
    score: Optional[float] = None
    passed: Optional[bool] = None
    details: Optional[dict] = None
    started_at: Optional[float] = None
    duration_s: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "step_count": self.step_count,
            "current_step": self.current_step,
            "responses": self.responses,
            "score": self.score,
            "passed": self.passed,
            "details": self.details,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TestProgress":
        return cls(
            name=d["name"],
            category=d["category"],
            description=d["description"],
            step_count=d["step_count"],
            current_step=d.get("current_step", 0),
            responses=d.get("responses", []),
            score=d.get("score"),
            passed=d.get("passed"),
            details=d.get("details"),
            started_at=None,
            duration_s=d.get("duration_s"),
        )


class GauntletRunner:
    """Stateful runner for MCP benchmark execution.

    Usage:
        runner = GauntletRunner(quick=False)
        result = runner.advance()            # starts, returns first prompt
        result = runner.advance("my answer") # submits response, returns next prompt or result
        ...until result["status"] == "complete"
    """

    def __init__(self, quick: bool = False, client_name: str = "unknown",
                 needle_secrets: Optional[list[int]] = None):
        self.quick = quick
        self.client_name = client_name
        self.suite = get_suite(quick, needle_secrets=needle_secrets)
        self.total_tests = len(self.suite)
        self.current_test_idx = 0
        self.current_test: Optional[TestProgress] = None
        self.completed: list[TestProgress] = []
        self.started = False
        self.finished = False
        self._run_start: Optional[float] = None
        self._elapsed_before_restore: float = 0.0

    def advance(self, response: Optional[str] = None) -> dict:
        """Advance the state machine.

        Args:
            response: The AI's response to the previous prompt. None on first call.

        Returns:
            dict with keys:
                status: "prompt" | "result" | "complete"
                + additional fields depending on status
        """
        # First call — start the benchmark
        if not self.started:
            self.started = True
            self._run_start = time.perf_counter()
            return self._start_next_test()

        # We're expecting a response
        if self.current_test is None:
            return {"status": "error", "message": "No active test. Start a new run."}

        if response is None:
            return {"status": "error", "message": "Expected a response to the previous prompt."}

        # Record the response
        self.current_test.responses.append(response)
        self.current_test.current_step += 1

        # Check if there are more steps in this test
        probe = self.suite[self.current_test_idx - 1]  # -1 because we already incremented
        steps = probe["steps"]

        if self.current_test.current_step < len(steps):
            # More steps — send next prompt
            return self._send_step(probe, self.current_test.current_step)

        # All steps done — verify
        verify = probe["verify"]
        score, passed, details = verify(self.current_test.responses)

        self.current_test.score = score
        self.current_test.passed = passed
        self.current_test.details = details
        self.current_test.duration_s = time.perf_counter() - (self.current_test.started_at or 0)

        self.completed.append(self.current_test)

        # Format the result
        test_result = self._format_test_result(self.current_test)

        # Move to next test
        if self.current_test_idx < self.total_tests:
            next_prompt = self._start_next_test()
            # Combine: show result of previous test + prompt for next
            return {
                "status": "prompt",
                "test_result": test_result,
                "test_number": self.current_test_idx,
                "total_tests": self.total_tests,
                "prompt": next_prompt["prompt"],
                "test_name": next_prompt["test_name"],
                "test_category": next_prompt["test_category"],
                "step": next_prompt.get("step"),
                "total_steps": next_prompt.get("total_steps"),
                "message": next_prompt["message"],
                "previous_result": test_result,
            }
        else:
            # All done
            self.finished = True
            return self._build_final_report()

    def _start_next_test(self) -> dict:
        """Initialize the next test and return its first prompt."""
        if self.current_test_idx >= self.total_tests:
            self.finished = True
            return self._build_final_report()

        probe = self.suite[self.current_test_idx]
        self.current_test = TestProgress(
            name=probe["name"],
            category=probe["category"],
            description=probe["description"],
            step_count=len(probe["steps"]),
            started_at=time.perf_counter(),
        )
        self.current_test_idx += 1
        return self._send_step(probe, 0)

    def _send_step(self, probe: dict, step_idx: int) -> dict:
        """Build the prompt message for a given step."""
        step = probe["steps"][step_idx]

        # Resolve prompt (may be a callable for multi-turn)
        if callable(step.get("prompt")):
            prompt_text = step["prompt"](self.current_test.responses)
        else:
            prompt_text = step["prompt"]

        total_steps = len(probe["steps"])
        is_followup = step_idx > 0

        # Build the message the AI sees
        if is_followup:
            header = f"[TEST {self.current_test_idx}/{self.total_tests}: {probe['name']} — Follow-up {step_idx + 1}/{total_steps}]"
        else:
            header = f"[TEST {self.current_test_idx}/{self.total_tests}: {probe['name']}]"

        # Show progress bar
        done = len(self.completed)
        passed = sum(1 for t in self.completed if t.passed)
        failed = done - passed
        progress = f"Progress: {done}/{self.total_tests} complete"
        if done > 0:
            progress += f" ({passed} passed, {failed} failed)"

        message = f"{header}\n{progress}\n\n"

        if is_followup and self.current_test.responses:
            message += f"Your previous response: \"{self.current_test.responses[-1].strip()[:200]}\"\n\n"

        message += f"Answer the following prompt, then call gauntlet_run with your response.\n\n"
        message += f"PROMPT: {prompt_text}"

        return {
            "status": "prompt",
            "test_number": self.current_test_idx,
            "total_tests": self.total_tests,
            "test_name": probe["name"],
            "test_category": probe["category"],
            "prompt": prompt_text,
            "step": step_idx + 1,
            "total_steps": total_steps,
            "message": message,
        }

    # ------------------------------------------------------------------
    # Serialization (for serverless state persistence)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize runner state to a JSON-safe dict."""
        needle_secrets = [
            p.get("_needle_secret") for p in self.suite if p.get("_needle_secret") is not None
        ]
        elapsed = self._elapsed_before_restore
        if self._run_start is not None:
            elapsed += time.perf_counter() - self._run_start

        return {
            "quick": self.quick,
            "client_name": self.client_name,
            "needle_secrets": needle_secrets,
            "current_test_idx": self.current_test_idx,
            "current_test": self.current_test.to_dict() if self.current_test else None,
            "completed": [t.to_dict() for t in self.completed],
            "started": self.started,
            "finished": self.finished,
            "elapsed_s": round(elapsed, 3),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GauntletRunner":
        """Reconstruct a runner from serialized state."""
        runner = cls(
            quick=d["quick"],
            client_name=d["client_name"],
            needle_secrets=d.get("needle_secrets"),
        )
        runner.current_test_idx = d["current_test_idx"]
        runner.current_test = (
            TestProgress.from_dict(d["current_test"]) if d.get("current_test") else None
        )
        runner.completed = [TestProgress.from_dict(t) for t in d.get("completed", [])]
        runner.started = d["started"]
        runner.finished = d["finished"]
        runner._elapsed_before_restore = d.get("elapsed_s", 0.0)
        runner._run_start = time.perf_counter() if runner.started and not runner.finished else None
        return runner

    def _format_test_result(self, test: TestProgress) -> str:
        """Format a single test result for display."""
        icon = "PASS" if test.passed else "FAIL"
        score_pct = round(test.score * 100) if test.score is not None else 0
        dur = f" ({test.duration_s:.1f}s)" if test.duration_s else ""
        return f"{icon}  {test.name} — {score_pct}%{dur} [{test.category}]"

    def _build_final_report(self) -> dict:
        """Build the complete benchmark report."""
        total_dur = self._elapsed_before_restore
        if self._run_start is not None:
            total_dur += time.perf_counter() - self._run_start

        # Category scores
        cats: dict[str, list[float]] = {}
        for t in self.completed:
            if t.score is not None:
                cats.setdefault(t.category, []).append(t.score)
        category_scores = {cat: sum(s) / len(s) for cat, s in cats.items()}
        overall = sum(category_scores.values()) / len(category_scores) if category_scores else 0

        passed = sum(1 for t in self.completed if t.passed)
        failed = len(self.completed) - passed

        # Build text report
        lines = [
            "=" * 60,
            f"  GAUNTLET COMPLETE — Score: {round(overall * 100)}%",
            f"  {passed}/{len(self.completed)} tests passed  |  {round(total_dur, 1)}s total",
            "=" * 60,
            "",
        ]

        # Per-test results
        for t in self.completed:
            lines.append(f"  {'PASS' if t.passed else 'FAIL'}  {t.name:<35s} {round(t.score * 100):>3d}%  [{t.category}]")
        lines.append("")

        # Category breakdown
        lines.append("  CATEGORY BREAKDOWN:")
        for cat, score in sorted(category_scores.items()):
            bar_len = int(score * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"    {cat:<25s} {bar} {round(score * 100):>3d}%")

        lines.append("")
        lines.append(f"  Client: {self.client_name}")
        lines.append(f"  Suite: {'Quick (7 tests)' if self.quick else 'Full (17 tests)'}")
        lines.append("=" * 60)

        report_text = "\n".join(lines)

        # Structured result for persistence
        result_dict = {
            "model": self.client_name,
            "overall_score": round(overall * 100, 1),
            "total_passed": passed,
            "total_tests": len(self.completed),
            "total_duration_s": round(total_dur, 1),
            "category_scores": {k: round(v * 100, 1) for k, v in category_scores.items()},
            "results": [
                {
                    "name": t.name,
                    "category": t.category,
                    "description": t.description,
                    "passed": t.passed,
                    "score_pct": round(t.score * 100, 1) if t.score is not None else 0,
                    "duration_s": round(t.duration_s, 2) if t.duration_s else None,
                    "details": t.details or {},
                }
                for t in self.completed
            ],
        }

        return {
            "status": "complete",
            "message": report_text,
            "result": result_dict,
        }
