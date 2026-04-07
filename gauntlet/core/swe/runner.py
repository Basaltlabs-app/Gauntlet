"""SWE test runner -- sends buggy code to models, verifies fixes in Docker."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from gauntlet.core.config import resolve_model
from gauntlet.core.providers.factory import create_provider
from gauntlet.core.swe.container import ContainerResult, check_docker, run_in_container
from gauntlet.core.swe.sandbox import run_in_sandbox, check_sandbox
from gauntlet.core.swe.test_packs import BUILT_IN_PACKS, TestPack, TestCase


@dataclass
class SWETestResult:
    """Result from one model attempting one SWE test case."""
    model: str
    test_case: str
    category: str
    passed: bool
    tests_passed: int
    tests_total: int
    model_response: str = ""
    container_output: str = ""
    duration_s: float = 0.0
    error: Optional[str] = None


@dataclass
class SWESuiteResult:
    """Results from running a full SWE suite against one model."""
    model: str
    results: list[SWETestResult] = field(default_factory=list)
    total_passed: int = 0
    total_tests: int = 0
    total_duration_s: float = 0.0
    categories: dict = field(default_factory=dict)  # category -> {passed, total}

    def compute(self) -> None:
        self.total_passed = sum(1 for r in self.results if r.passed)
        self.total_tests = len(self.results)
        self.total_duration_s = sum(r.duration_s for r in self.results)
        cats: dict[str, dict] = {}
        for r in self.results:
            if r.category not in cats:
                cats[r.category] = {"passed": 0, "total": 0}
            cats[r.category]["total"] += 1
            if r.passed:
                cats[r.category]["passed"] += 1
        self.categories = cats

    @property
    def pass_rate(self) -> float:
        return self.total_passed / self.total_tests if self.total_tests > 0 else 0

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "total_passed": self.total_passed,
            "total_tests": self.total_tests,
            "pass_rate": round(self.pass_rate * 100, 1),
            "total_duration_s": round(self.total_duration_s, 1),
            "categories": self.categories,
            "results": [
                {
                    "test_case": r.test_case,
                    "category": r.category,
                    "passed": r.passed,
                    "tests_passed": r.tests_passed,
                    "tests_total": r.tests_total,
                    "duration_s": round(r.duration_s, 2),
                    "error": r.error,
                }
                for r in self.results
            ],
        }


SWE_SYSTEM_PROMPT = (
    "You are a senior software engineer fixing bugs in a codebase. "
    "You will be given the current code and a bug report. "
    "Return ONLY the complete fixed file. No explanation, no markdown fencing, "
    "just the corrected Python code."
)


async def run_swe_test(
    model_spec: str,
    test_case: TestCase,
    use_docker: bool = False,
) -> SWETestResult:
    """Run one SWE test case against one model.

    1. Send the buggy code + issue to the model
    2. Get the model's fix
    3. Run the fix in a Docker container against the test suite
    4. Report pass/fail
    """
    start = time.perf_counter()

    # Build prompt
    prompt = (
        f"## Bug Report\n{test_case.issue}\n\n"
        f"## Current Code ({test_case.filename})\n"
        f"```python\n{test_case.buggy_code}\n```\n\n"
        f"Fix the bug. Return ONLY the complete corrected file."
    )

    # Get model's fix
    config = resolve_model(model_spec)
    provider, model_name = create_provider(config)

    parts = []
    try:
        async for chunk in provider.stream_generate(
            model=model_name, prompt=prompt, system=SWE_SYSTEM_PROMPT,
        ):
            parts.append(chunk.text)
            if chunk.done:
                break
    except Exception as e:
        return SWETestResult(
            model=model_spec, test_case=test_case.name,
            category=test_case.category, passed=False,
            tests_passed=0, tests_total=test_case.expected_tests,
            error=f"Model error: {e}",
            duration_s=time.perf_counter() - start,
        )

    model_response = "".join(parts).strip()

    # Clean markdown fencing if present
    import re
    if "```" in model_response:
        match = re.search(r"```(?:python)?\s*(.*?)```", model_response, re.DOTALL)
        if match:
            model_response = match.group(1).strip()

    # Run tests -- sandbox (default) or Docker
    try:
        if use_docker and check_docker():
            result = run_in_container(
                image=test_case.docker_image,
                fix_code=model_response,
                test_code=test_case.test_code,
                test_command=test_case.test_command,
                timeout=test_case.timeout,
            )
        else:
            result = run_in_sandbox(
                fix_code=model_response,
                test_code=test_case.test_code,
                timeout=test_case.timeout,
            )

        return SWETestResult(
            model=model_spec, test_case=test_case.name,
            category=test_case.category,
            passed=result.all_passed,
            tests_passed=result.tests_passed,
            tests_total=result.tests_total or test_case.expected_tests,
            model_response=model_response[:1000],
            container_output=result.stdout[:500],
            duration_s=time.perf_counter() - start,
        )

    except Exception as e:
        return SWETestResult(
            model=model_spec, test_case=test_case.name,
            category=test_case.category, passed=False,
            tests_passed=0, tests_total=test_case.expected_tests,
            error=f"Execution error: {e}",
            model_response=model_response[:500],
            duration_s=time.perf_counter() - start,
        )


async def run_swe_suite(
    model_spec: str,
    test_pack: Optional[str] = None,
    use_docker: bool = False,
    on_progress=None,
) -> SWESuiteResult:
    """Run the full SWE suite against one model."""
    packs = BUILT_IN_PACKS if test_pack is None else [
        p for p in BUILT_IN_PACKS if p.name == test_pack
    ]

    all_cases = []
    for pack in packs:
        all_cases.extend(pack.cases)

    result = SWESuiteResult(model=model_spec)

    for i, case in enumerate(all_cases):
        if on_progress:
            on_progress(model_spec, i + 1, len(all_cases), case.name)

        test_result = await run_swe_test(model_spec, case, use_docker=use_docker)
        result.results.append(test_result)

    result.compute()
    return result


async def run_swe_comparison(
    model_specs: list[str],
    test_pack: Optional[str] = None,
    use_docker: bool = False,
) -> list[SWESuiteResult]:
    """Run SWE suite against multiple models (sequentially for fairness)."""
    results = []
    for spec in model_specs:
        r = await run_swe_suite(spec, test_pack=test_pack, use_docker=use_docker)
        results.append(r)
    return results
