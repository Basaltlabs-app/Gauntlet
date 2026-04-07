"""Auto-judge system -- uses a model to score all outputs."""

from __future__ import annotations

import json
import re
from typing import Optional

from gauntlet.core.config import resolve_model
from gauntlet.core.metrics import ComparisonResult, ModelMetrics
from gauntlet.core.providers.factory import create_provider


JUDGE_SYSTEM_PROMPT = """You are an expert judge evaluating AI model outputs. You will be given a prompt and multiple model responses. Score each response on these dimensions:

1. **Correctness** (1-10): Is the answer factually accurate and free of errors?
2. **Completeness** (1-10): Does it fully address the prompt?
3. **Clarity** (1-10): Is it well-organized and easy to understand?
4. **Code Quality** (1-10): If code is present, is it clean, efficient, and correct? If no code, score based on writing quality.

Respond ONLY with valid JSON in this exact format:
{
  "results": [
    {
      "model": "<model_name>",
      "correctness": <1-10>,
      "completeness": <1-10>,
      "clarity": <1-10>,
      "code_quality": <1-10>,
      "overall": <1-10>,
      "reasoning": "<brief explanation>"
    }
  ],
  "winner": "<model_name>"
}"""


def _build_judge_prompt(prompt: str, models: list[ModelMetrics]) -> str:
    """Build the prompt for the judge model."""
    parts = [f'Original prompt: """{prompt}"""\n']

    for i, m in enumerate(models, 1):
        output = m.output
        if output.startswith("[ERROR]"):
            output = "(Model failed to generate a response)"
        # Truncate very long outputs for the judge
        if len(output) > 4000:
            output = output[:4000] + "\n... (truncated)"
        parts.append(f'--- Response from {m.model} ---\n"""{output}"""\n')

    parts.append(
        "Score each response. Remember to respond ONLY with valid JSON."
    )
    return "\n".join(parts)


def _parse_judge_response(text: str, models: list[ModelMetrics]) -> dict:
    """Parse the judge's JSON response, handling common formatting issues."""
    # Try to extract JSON from the response
    # Sometimes models wrap JSON in markdown code blocks
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        # Try to find raw JSON
        brace_start = text.find("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            text = text[brace_start:brace_end]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: return equal scores
        model_names = [m.model for m in models]
        return {
            "results": [
                {
                    "model": name,
                    "correctness": 5,
                    "completeness": 5,
                    "clarity": 5,
                    "code_quality": 5,
                    "overall": 5,
                    "reasoning": "Judge response could not be parsed",
                }
                for name in model_names
            ],
            "winner": model_names[0] if model_names else None,
        }

    return data


async def judge_comparison(
    comparison: ComparisonResult,
    judge_model: str = "auto",
) -> ComparisonResult:
    """Score all model outputs using a judge model.

    Args:
        comparison: The comparison result to judge
        judge_model: Model spec for the judge. "auto" picks the best available.

    Returns:
        The same ComparisonResult with quality_scores and winner filled in.
    """
    # Filter out models that errored
    valid_models = [m for m in comparison.models if not m.output.startswith("[ERROR]")]
    if not valid_models:
        return comparison

    # Resolve judge model
    if judge_model == "auto":
        judge_model = await _pick_judge_model(comparison.models)

    config = resolve_model(judge_model)
    provider, model_name = create_provider(config)

    judge_prompt = _build_judge_prompt(comparison.prompt, valid_models)

    # Generate judge response with timeout and token limit
    import time
    output_parts = []
    token_count = 0
    start = time.perf_counter()
    async for chunk in provider.stream_generate(
        model=model_name,
        prompt=judge_prompt,
        system=JUDGE_SYSTEM_PROMPT,
    ):
        output_parts.append(chunk.text)
        token_count += 1
        if chunk.done:
            break
        # Hard limits to prevent hanging
        if token_count >= 1500:
            break
        if time.perf_counter() - start > 90:
            break

    judge_text = "".join(output_parts)
    parsed = _parse_judge_response(judge_text, valid_models)

    # Apply scores to metrics
    results_by_model = {}
    for r in parsed.get("results", []):
        results_by_model[r.get("model", "")] = r

    for m in comparison.models:
        scores = results_by_model.get(m.model, {})
        if scores:
            m.quality_scores = {
                "correctness": scores.get("correctness", 5),
                "completeness": scores.get("completeness", 5),
                "clarity": scores.get("clarity", 5),
                "code_quality": scores.get("code_quality", 5),
            }
            m.overall_score = scores.get("overall", 5)

    # Judge no longer picks the winner -- composite scoring does that
    comparison.judge_model = judge_model

    return comparison


async def _pick_judge_model(models: list[ModelMetrics]) -> str:
    """Auto-select the best available judge model.

    Prefers large local models, falls back to the first available model
    that isn't in the comparison set.
    """
    from gauntlet.core.providers.ollama import OllamaProvider

    compared_models = {m.model for m in models}

    # Try to find a local model not in the comparison
    try:
        ollama = OllamaProvider()
        if await ollama.check_connection():
            available = await ollama.list_models()
            # Sort by size (largest first) to pick the best judge
            available.sort(key=lambda x: x.get("size", 0) or 0, reverse=True)
            for m in available:
                name = m["name"]
                # Skip models that are being compared
                if name not in compared_models and name.split(":")[0] not in compared_models:
                    return name
    except Exception:
        pass

    # Fallback: use the first compared model as judge (not ideal but works)
    return models[0].model if models else "llama3.2"
