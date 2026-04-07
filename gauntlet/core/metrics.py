"""Performance metrics collection for model comparisons."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import psutil


@dataclass
class ModelMetrics:
    """Performance metrics for a single model run."""

    model: str
    provider: str

    # Timing
    ttft_ms: Optional[float] = None  # Time to first token (milliseconds)
    total_time_s: Optional[float] = None  # Total generation time (seconds)
    tokens_per_sec: Optional[float] = None  # Generation speed

    # Token counts
    total_tokens: int = 0
    prompt_tokens: Optional[int] = None

    # Memory
    memory_before_mb: Optional[float] = None
    memory_after_mb: Optional[float] = None
    peak_memory_delta_mb: Optional[float] = None

    # Quality (filled by judge)
    quality_scores: dict = field(default_factory=dict)
    overall_score: Optional[float] = None

    # The generated text
    output: str = ""

    # Streaming state (used during generation, not in final output)
    _start_time: Optional[float] = field(default=None, repr=False)
    _first_token_time: Optional[float] = field(default=None, repr=False)
    _token_count: int = field(default=0, repr=False)

    def start(self) -> None:
        """Mark the start of generation."""
        self._start_time = time.perf_counter()
        self.memory_before_mb = _get_system_memory_mb()

    def record_first_token(self) -> None:
        """Record when the first token arrives."""
        if self._first_token_time is None and self._start_time is not None:
            self._first_token_time = time.perf_counter()
            self.ttft_ms = (self._first_token_time - self._start_time) * 1000

    def record_token(self, text: str) -> None:
        """Record a token being received."""
        self._token_count += 1
        self.output += text

    def finish(self, provider_meta: dict | None = None) -> None:
        """Finalize metrics after generation completes."""
        end_time = time.perf_counter()
        self.memory_after_mb = _get_system_memory_mb()

        if self._start_time is not None:
            self.total_time_s = end_time - self._start_time

        if self.memory_before_mb is not None and self.memory_after_mb is not None:
            self.peak_memory_delta_mb = self.memory_after_mb - self.memory_before_mb

        # Use provider-reported metrics if available (more accurate)
        if provider_meta:
            eval_count = provider_meta.get("eval_count")
            eval_duration = provider_meta.get("eval_duration")

            if eval_count and eval_duration:
                # Ollama reports eval_duration in nanoseconds
                self.total_tokens = eval_count
                self.tokens_per_sec = eval_count / (eval_duration / 1e9)
            else:
                # Cloud providers -- use our own measurements
                output_tokens = provider_meta.get("output_tokens")
                if output_tokens:
                    self.total_tokens = output_tokens

            prompt_tokens = provider_meta.get("prompt_eval_count") or provider_meta.get(
                "prompt_tokens"
            ) or provider_meta.get("input_tokens")
            if prompt_tokens:
                self.prompt_tokens = prompt_tokens

            # For cloud providers, extract usage from nested dict
            usage = provider_meta.get("usage", {})
            if usage:
                self.total_tokens = self.total_tokens or usage.get(
                    "completion_tokens", 0
                )
                self.prompt_tokens = self.prompt_tokens or usage.get("prompt_tokens")

        # Fallback: calculate from our own timing
        if not self.total_tokens:
            self.total_tokens = self._token_count

        if not self.tokens_per_sec and self.total_time_s and self.total_time_s > 0:
            # Subtract TTFT to get pure generation time
            gen_time = self.total_time_s
            if self.ttft_ms:
                gen_time -= self.ttft_ms / 1000
            if gen_time > 0 and self.total_tokens > 0:
                self.tokens_per_sec = self.total_tokens / gen_time

    def to_dict(self) -> dict:
        """Serialize to a plain dict (for JSON/WebSocket)."""
        return {
            "model": self.model,
            "provider": self.provider,
            "ttft_ms": round(self.ttft_ms, 1) if self.ttft_ms else None,
            "total_time_s": round(self.total_time_s, 2) if self.total_time_s else None,
            "tokens_per_sec": (
                round(self.tokens_per_sec, 1) if self.tokens_per_sec else None
            ),
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "peak_memory_delta_mb": (
                round(self.peak_memory_delta_mb, 1)
                if self.peak_memory_delta_mb is not None
                else None
            ),
            "quality_scores": self.quality_scores,
            "overall_score": self.overall_score,
            "output": self.output,
        }


@dataclass
class ScoreWeights:
    """Weights for composite scoring. Must sum to 1.0."""

    speed: float = 0.30
    quality: float = 0.50
    responsiveness: float = 0.20

    def redistribute_without_quality(self) -> "ScoreWeights":
        """When --no-judge is used, redistribute quality weight."""
        total = self.speed + self.responsiveness
        return ScoreWeights(
            speed=self.speed / total,
            quality=0.0,
            responsiveness=self.responsiveness / total,
        )


@dataclass
class ComponentScore:
    """A single scoring dimension for one model."""

    metric_name: str       # "Speed", "Quality", "Responsiveness"
    raw_value: float       # e.g. 45.2
    raw_unit: str          # e.g. "tok/s"
    normalized: float      # 0.0 - 1.0 (relative to best in group)
    weight: float          # the weight applied
    weighted: float        # normalized * weight
    rank: int              # 1-indexed rank in this dimension


@dataclass
class ModelCompositeScore:
    """All scoring components for one model."""

    model: str
    components: list[ComponentScore]
    composite: float       # sum of all weighted scores
    rank: int              # overall rank


@dataclass
class ScoringBreakdown:
    """The complete scoring explanation."""

    weights: ScoreWeights
    model_scores: list[ModelCompositeScore]
    winner: Optional[str]
    winner_reason: str     # human-readable: "Won Speed (45.2 vs 32.1 tok/s)..."
    formula: str           # "Speed(30%) + Quality(50%) + Responsiveness(20%)"

    def to_dict(self) -> dict:
        return {
            "formula": self.formula,
            "winner": self.winner,
            "winner_reason": self.winner_reason,
            "models": [
                {
                    "model": ms.model,
                    "composite": round(ms.composite, 3),
                    "rank": ms.rank,
                    "components": [
                        {
                            "metric": c.metric_name,
                            "raw": f"{c.raw_value:.1f} {c.raw_unit}",
                            "normalized": round(c.normalized, 3),
                            "weight": f"{c.weight:.0%}",
                            "weighted": round(c.weighted, 3),
                            "rank": c.rank,
                        }
                        for c in ms.components
                    ],
                }
                for ms in self.model_scores
            ],
        }


@dataclass
class ComparisonResult:
    """Complete result of a multi-model comparison."""

    prompt: str
    models: list[ModelMetrics]
    winner: Optional[str] = None
    judge_model: Optional[str] = None
    timestamp: Optional[str] = None
    scoring: Optional[ScoringBreakdown] = None

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        d = {
            "prompt": self.prompt,
            "models": [m.to_dict() for m in self.models],
            "winner": self.winner,
            "judge_model": self.judge_model,
            "timestamp": self.timestamp,
        }
        if self.scoring:
            d["scoring"] = self.scoring.to_dict()
        return d


def compute_composite_scores(
    result: "ComparisonResult",
    weights: Optional[ScoreWeights] = None,
    has_quality: bool = True,
) -> Optional[ScoringBreakdown]:
    """Compute transparent composite scores to determine a winner.

    Each metric is normalized 0-1 relative to the best performer:
      - Speed: model_tps / max_tps (higher is better)
      - Responsiveness: min_ttft / model_ttft (lower is better, inverted)
      - Quality: model.overall_score / 10 (from judge, or 0 if no judge)

    Returns ScoringBreakdown with full explanation of why the winner won.
    """
    valid = [m for m in result.models if not m.output.startswith("[ERROR]")]
    if not valid:
        return None

    w = weights or ScoreWeights()
    if not has_quality:
        w = w.redistribute_without_quality()

    # Build formula string
    parts = []
    if w.speed > 0:
        parts.append(f"Speed({w.speed:.0%})")
    if w.quality > 0:
        parts.append(f"Quality({w.quality:.0%})")
    if w.responsiveness > 0:
        parts.append(f"Responsiveness({w.responsiveness:.0%})")
    formula = " + ".join(parts)

    # Gather raw values
    speeds = {m.model: (m.tokens_per_sec or 0) for m in valid}
    ttfts = {m.model: (m.ttft_ms or 999999) for m in valid}
    qualities = {m.model: (m.overall_score or 0) for m in valid}

    max_speed = max(speeds.values()) or 1
    min_ttft = min(v for v in ttfts.values() if v > 0) if any(v > 0 for v in ttfts.values()) else 1

    # Normalize and rank each dimension
    def _rank(values: dict, higher_better: bool) -> dict:
        sorted_items = sorted(values.items(), key=lambda x: x[1], reverse=higher_better)
        return {name: rank + 1 for rank, (name, _) in enumerate(sorted_items)}

    speed_ranks = _rank(speeds, higher_better=True)
    ttft_ranks = _rank(ttfts, higher_better=False)
    quality_ranks = _rank(qualities, higher_better=True)

    # Build per-model composite scores
    model_scores = []
    for m in valid:
        components = []

        # Speed
        norm_speed = speeds[m.model] / max_speed if max_speed > 0 else 0
        components.append(ComponentScore(
            metric_name="Speed", raw_value=speeds[m.model], raw_unit="tok/s",
            normalized=norm_speed, weight=w.speed,
            weighted=norm_speed * w.speed, rank=speed_ranks[m.model],
        ))

        # Responsiveness (TTFT inverted -- lower is better)
        raw_ttft = ttfts[m.model]
        norm_resp = min_ttft / raw_ttft if raw_ttft > 0 else 0
        components.append(ComponentScore(
            metric_name="Responsiveness", raw_value=raw_ttft, raw_unit="ms TTFT",
            normalized=norm_resp, weight=w.responsiveness,
            weighted=norm_resp * w.responsiveness, rank=ttft_ranks[m.model],
        ))

        # Quality (only if judge was used)
        if w.quality > 0:
            norm_quality = qualities[m.model] / 10
            components.append(ComponentScore(
                metric_name="Quality", raw_value=qualities[m.model], raw_unit="/10",
                normalized=norm_quality, weight=w.quality,
                weighted=norm_quality * w.quality, rank=quality_ranks[m.model],
            ))

        composite = sum(c.weighted for c in components)
        model_scores.append(ModelCompositeScore(
            model=m.model, components=components, composite=composite, rank=0,
        ))

    # Rank by composite
    model_scores.sort(key=lambda x: x.composite, reverse=True)
    for i, ms in enumerate(model_scores):
        ms.rank = i + 1

    winner = model_scores[0].model if model_scores else None

    # Build winner reason
    reason_parts = []
    if len(model_scores) >= 2:
        best = model_scores[0]
        second = model_scores[1]
        reason_parts.append(
            f"{best.model} scored {best.composite:.2f} vs {second.model} at {second.composite:.2f}"
        )
        # Which components did the winner lead?
        for comp in best.components:
            other_comp = next(
                (c for ms in model_scores[1:] for c in ms.components if c.metric_name == comp.metric_name),
                None,
            )
            if other_comp and comp.rank == 1:
                reason_parts.append(
                    f"Led {comp.metric_name}: {comp.raw_value:.1f} {comp.raw_unit} vs {other_comp.raw_value:.1f} {other_comp.raw_unit}"
                )
            elif other_comp and comp.rank > 1:
                reason_parts.append(
                    f"Trailed {comp.metric_name}: {comp.raw_value:.1f} {comp.raw_unit} vs {other_comp.raw_value:.1f} {other_comp.raw_unit}"
                )
    elif len(model_scores) == 1:
        reason_parts.append(f"{model_scores[0].model} was the only model that completed")

    winner_reason = ". ".join(reason_parts)

    return ScoringBreakdown(
        weights=w, model_scores=model_scores,
        winner=winner, winner_reason=winner_reason, formula=formula,
    )


def _get_system_memory_mb() -> float:
    """Get current process memory usage in MB."""
    process = psutil.Process()
    return process.memory_info().rss / (1024 * 1024)
