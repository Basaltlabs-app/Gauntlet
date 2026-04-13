"""Health check runner -- orchestrates the quick health check with LLM judging and regression detection."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

logger = logging.getLogger("gauntlet.health_runner")


@dataclass
class RegressionInfo:
    previous_score: float
    score_delta: float
    previous_date: str
    is_regression: bool      # delta < -10
    is_improvement: bool     # delta > +10
    anchor_drift: float      # change in hc_15 score

    def to_dict(self):
        return asdict(self)


@dataclass
class HealthCheckResult:
    model: str
    overall_score: float          # 0-100
    grade: str
    tokens_per_sec: float
    time_to_first_token_ms: float
    category_scores: dict         # {writing, code, reasoning, summarization, data_analysis, creative}
    probe_results: list[dict]
    total_duration_s: float
    regression: Optional[RegressionInfo] = None
    judge_type: str = "self"
    hardware_tier: str = "unknown"

    def to_dict(self):
        d = asdict(self)
        if self.regression:
            d["regression"] = self.regression.to_dict()
        return d


async def run_health_check(
    model_spec: str,
    on_probe_done: Optional[Callable] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    judge_model: str = "auto",
) -> HealthCheckResult:
    """Run the quick health check with hybrid LLM judging.

    Flow:
    1. Run 15 probes via HealthCheck module
    2. Score deterministic probes immediately
    3. Score LLM-judged probes via health_judge
    4. Compute category scores and overall
    5. Load previous results, detect regression
    6. Save locally, submit to community
    7. Return HealthCheckResult
    """
    from gauntlet.core.config import detect_provider
    from gauntlet.core.client import ChatClient
    from gauntlet.core.modules.health_check import HealthCheck
    from gauntlet.core.health_judge import judge_response, get_available_judge
    from gauntlet.core.benchmark_history import save_health_check, get_latest_health

    provider, model_name = detect_provider(model_spec)

    # Create client
    client = ChatClient(model_name=model_name, provider=provider)

    # Run all 15 probes
    module = HealthCheck()
    config = {}
    if on_probe_done:
        config["on_probe_complete"] = on_probe_done
    if cancel_check:
        config["cancel_check"] = cancel_check

    t0 = time.perf_counter()
    result = await module.run(client, config)
    total_duration = time.perf_counter() - t0

    # Extract speed metrics from specific probes
    ttft_ms = 0.0
    tok_per_sec = 0.0
    for pr in result.probe_results:
        if pr.probe_id == "hc_01":  # warmup -- approximates TTFT
            ttft_ms = pr.duration_s * 1000
        elif pr.probe_id == "hc_02":  # throughput
            word_count = len(pr.model_output.split())
            if pr.duration_s > 0:
                tok_per_sec = word_count / pr.duration_s  # rough estimate

    # Run LLM judge on probes that need it
    actual_judge = judge_model
    if judge_model == "auto":
        actual_judge = get_available_judge()

    judge_type_used = "deterministic"
    for pr in result.probe_results:
        # Find the original probe to get rubric
        probes = module.build_probes()
        probe = next((p for p in probes if p.id == pr.probe_id), None)
        if not probe:
            continue

        rubric = probe.meta.get("judge_rubric")
        checker = probe.meta.get("checker_type", "deterministic")

        if rubric and checker in ("llm_only", "deterministic_plus_llm", "code_deterministic"):
            # Get the original prompt text
            original_prompt = probe.messages[0][1] if probe.messages else ""

            jr = await judge_response(
                probe_name=probe.name,
                original_prompt=original_prompt,
                model_output=pr.model_output,
                rubric=rubric,
                model_spec=model_spec,
                judge_model=actual_judge,
            )

            if checker == "llm_only":
                # LLM judge is the only score
                pr.score = jr.score
                pr.passed = jr.score >= 0.5
                pr.reason = jr.reasoning
            elif checker in ("deterministic_plus_llm", "code_deterministic"):
                # Blend: 60% deterministic + 40% LLM judge
                det_score = pr.score
                pr.score = round(0.6 * det_score + 0.4 * jr.score, 3)
                pr.passed = pr.score >= 0.5
                if jr.reasoning:
                    pr.reason += f" | Judge: {jr.reasoning}"

            if jr.judge_type != "deterministic":
                judge_type_used = jr.judge_type

    # Compute category scores
    categories = {}
    for pr in result.probe_results:
        cat = pr.meta.get("category", "unknown") if hasattr(pr, "meta") else "unknown"
        # Fall back to extracting from probe definitions
        if cat == "unknown":
            probe = next((p for p in module.build_probes() if p.id == pr.probe_id), None)
            if probe:
                cat = probe.meta.get("category", "unknown")

        if cat not in categories:
            categories[cat] = []
        categories[cat].append(pr.score)

    category_scores = {
        cat: round(sum(scores) / len(scores) * 100, 1)
        for cat, scores in categories.items()
        if cat != "regression_anchor"
    }

    # Overall score (exclude regression anchor)
    all_scores = [
        s
        for cat, scores in categories.items()
        if cat != "regression_anchor"
        for s in scores
    ]
    overall_score = round(sum(all_scores) / len(all_scores) * 100, 1) if all_scores else 0.0

    # Grade
    from gauntlet.core.modules.base import ModuleScore

    grade = ModuleScore.grade_from_score(overall_score / 100, 0)

    # Hardware tier
    try:
        from gauntlet.core.system_info import collect_fingerprint

        fp = collect_fingerprint(model_name, provider)
        hardware_tier = fp.hardware_tier or "unknown"
    except Exception:
        hardware_tier = "unknown"

    # Regression detection
    regression = None
    try:
        previous = get_latest_health(model_name)
        if previous:
            prev_score = previous.get("overall_score", 0)
            delta = overall_score - prev_score

            # Anchor drift
            anchor_current = 0.0
            anchor_prev = 0.0
            for pr in result.probe_results:
                probe = next((p for p in module.build_probes() if p.id == pr.probe_id), None)
                if probe and probe.meta.get("category") == "regression_anchor":
                    anchor_current = pr.score
            for ppr in previous.get("probe_results", []):
                if ppr.get("probe_id") == "hc_15":
                    anchor_prev = ppr.get("score", 0)

            regression = RegressionInfo(
                previous_score=prev_score,
                score_delta=round(delta, 1),
                previous_date=previous.get("timestamp", ""),
                is_regression=delta < -10,
                is_improvement=delta > 10,
                anchor_drift=round(anchor_current - anchor_prev, 3),
            )
    except Exception as e:
        logger.debug("Regression detection failed: %s", e)

    # Build result
    health_result = HealthCheckResult(
        model=model_name,
        overall_score=overall_score,
        grade=grade,
        tokens_per_sec=round(tok_per_sec, 1),
        time_to_first_token_ms=round(ttft_ms, 1),
        category_scores=category_scores,
        probe_results=[
            {
                "probe_id": pr.probe_id,
                "probe_name": pr.probe_name,
                "passed": pr.passed,
                "score": pr.score,
                "duration_s": pr.duration_s,
                "category": next(
                    (p.meta.get("category") for p in module.build_probes() if p.id == pr.probe_id),
                    "unknown",
                ),
            }
            for pr in result.probe_results
        ],
        total_duration_s=round(total_duration, 1),
        regression=regression,
        judge_type=judge_type_used,
        hardware_tier=hardware_tier,
    )

    # Save locally
    try:
        save_health_check(health_result.to_dict(), model_name)
    except Exception as e:
        logger.debug("Failed to save health check: %s", e)

    # Submit to community (non-blocking)
    import threading

    def _submit():
        try:
            from gauntlet.core.submit import submit_result, build_attestation
            from gauntlet.core.system_info import collect_fingerprint

            fp = collect_fingerprint(model_name, provider)
            hw, rt, mc = fp.to_storage_dicts()

            attestation = build_attestation(
                hardware_tier=fp.hardware_tier or "",
                suite_type="health_check",
                probe_count=15,
            )

            payload = {
                "model_name": model_name,
                "overall_score": overall_score,
                "trust_score": 0,  # health check doesn't compute trust
                "grade": grade,
                "category_scores": category_scores,
                "total_probes": 15,
                "passed_probes": sum(1 for pr in result.probe_results if pr.passed),
                "source": "dashboard",
                "quick": True,
                "hardware": hw,
                "runtime": rt,
                "model_config": mc,
                "gauntlet_version": "",
                "attestation": attestation,
                "hardware_tier": attestation.get("hardware_tier", ""),
                "tokens_per_sec": tok_per_sec,
                "ttft_ms": ttft_ms,
                "judge_type": judge_type_used,
            }

            try:
                import gauntlet

                payload["gauntlet_version"] = gauntlet.__version__
            except Exception:
                pass

            submit_result(payload)
        except Exception as e:
            logger.warning("Community submission failed: %s", e)

    t = threading.Thread(target=_submit, daemon=True)
    t.start()
    t.join(timeout=15)  # Wait up to 15s for submission to complete

    return health_result
