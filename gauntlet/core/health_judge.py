"""LLM judge for health check probe evaluation.

Scores health check responses using structured rubrics. Supports:
- External judge: a cloud model (GPT-4o-mini, Claude Haiku) provides objective scoring
- Deterministic fallback: keyword/length heuristics when no external API key is available

Self-judging (model grades itself) is NOT supported — a sycophantic model
would rate itself highly, producing unreliable scores. When no external API
key is configured, LLM-judged probes use deterministic heuristics instead.

Judge type is auto-detected from available API keys. Results include
which judge was used for transparency.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("gauntlet.health_judge")


@dataclass
class JudgeResult:
    """Result from judging a single health check probe response."""
    score: float           # 0.0-1.0
    reasoning: str         # judge's explanation
    judge_type: str        # "self", "external:gpt-4o-mini", "deterministic"
    criteria_scores: dict  # {criterion_name: score_0_to_1}


def get_available_judge() -> Optional[str]:
    """Auto-detect the best available external judge model from API keys.

    Returns model spec string or None if no external judge is available.
    When None, LLM-judged probes use deterministic heuristics only.
    Priority: OpenAI (cheapest) > Anthropic > Google > None
    """
    if os.environ.get("OPENAI_API_KEY"):
        return "openai:gpt-4o-mini"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic:claude-haiku"
    if os.environ.get("GOOGLE_API_KEY"):
        return "google:gemini-2.0-flash"
    return None


def build_judge_prompt(probe_name: str, rubric: dict, original_prompt: str, model_output: str) -> str:
    """Build the structured judge prompt from a rubric.

    rubric format: {
        "criteria": [
            {"name": "tone", "description": "Professional and polite", "weight": 1.0},
            {"name": "completeness", "description": "Includes decline, reason, and alternative", "weight": 1.0},
        ]
    }
    """
    criteria_text = "\n".join(
        f"  {i+1}. {c['name']}: {c.get('description', c.get('desc', ''))}"
        for i, c in enumerate(rubric["criteria"])
    )

    return f"""You are evaluating an AI model's response to a task. Rate the response on each criterion below on a scale of 0-10.

TASK: {original_prompt}

RESPONSE:
{model_output}

CRITERIA:
{criteria_text}

Rate each criterion 0-10 where 0=terrible, 5=adequate, 10=excellent.
Respond ONLY with valid JSON in this exact format:
{{"scores": {{{", ".join(f'"{c["name"]}": <0-10>' for c in rubric["criteria"])}}}, "reasoning": "<one sentence overall assessment>"}}"""


def parse_judge_output(output: str, rubric: dict) -> JudgeResult:
    """Parse the judge's JSON response into a JudgeResult.

    Handles malformed JSON gracefully with fallback scoring.
    """
    criteria_names = [c["name"] for c in rubric["criteria"]]
    criteria_weights = {c["name"]: c.get("weight", 1.0) for c in rubric["criteria"]}

    # Try to extract JSON from response
    json_match = re.search(r'\{[^{}]*"scores"[^{}]*\{[^{}]*\}[^{}]*\}', output, re.DOTALL)
    if not json_match:
        # Try simpler JSON extraction
        json_match = re.search(r'\{.*\}', output, re.DOTALL)

    if json_match:
        try:
            data = json.loads(json_match.group())
            scores_raw = data.get("scores", data)
            reasoning = data.get("reasoning", "")

            criteria_scores = {}
            for name in criteria_names:
                raw = scores_raw.get(name, 5)
                criteria_scores[name] = max(0.0, min(1.0, float(raw) / 10.0))

            # Weighted average
            total_weight = sum(criteria_weights.get(n, 1.0) for n in criteria_scores)
            weighted_sum = sum(
                criteria_scores[n] * criteria_weights.get(n, 1.0)
                for n in criteria_scores
            )
            overall = weighted_sum / total_weight if total_weight > 0 else 0.5

            return JudgeResult(
                score=round(overall, 3),
                reasoning=reasoning or "Scored via structured rubric",
                judge_type="",  # filled by caller
                criteria_scores=criteria_scores,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Fallback: couldn't parse judge output
    logger.warning("Could not parse judge output, using heuristic fallback")
    return _heuristic_fallback(output, rubric)


def _heuristic_fallback(model_output: str, rubric: dict) -> JudgeResult:
    """Fallback scoring when judge output can't be parsed.

    Uses length + keyword heuristics for a rough score.
    """
    # Basic heuristic: longer, more detailed responses score higher
    length = len(model_output.strip())
    if length < 50:
        score = 0.2
    elif length < 200:
        score = 0.4
    elif length < 500:
        score = 0.6
    else:
        score = 0.7

    criteria_scores = {c["name"]: score for c in rubric["criteria"]}

    return JudgeResult(
        score=score,
        reasoning="Scored via heuristic fallback (judge output unparseable)",
        judge_type="deterministic",
        criteria_scores=criteria_scores,
    )


async def judge_response(
    probe_name: str,
    original_prompt: str,
    model_output: str,
    rubric: dict,
    model_spec: str,
    judge_model: Optional[str] = "auto",
) -> JudgeResult:
    """Score a health check response using an external LLM judge or deterministic heuristics.

    Args:
        probe_name: Name of the probe being judged
        original_prompt: The original task prompt
        model_output: The model's response to evaluate
        rubric: Structured rubric with criteria and weights
        model_spec: The model being tested (not used for judging — no self-judge)
        judge_model: "auto" (detect from API keys), None (deterministic only),
                     or explicit model spec like "openai:gpt-4o-mini"

    Returns:
        JudgeResult with score, reasoning, judge_type, and per-criteria scores
    """
    from gauntlet.core.client import ChatClient
    from gauntlet.core.config import detect_provider

    # Determine judge model
    if judge_model == "auto":
        judge_model = get_available_judge()

    # No external judge available — use deterministic heuristics only.
    # Self-judging is not supported (biased: sycophantic models rate themselves highly).
    if not judge_model:
        return _heuristic_fallback(model_output, rubric)

    judge_prompt = build_judge_prompt(probe_name, rubric, original_prompt, model_output)

    judge_type = f"external:{judge_model.split(':')[-1]}"
    provider, model_name = detect_provider(judge_model)

    try:
        client = ChatClient(
            model_name=model_name,
            provider=provider,
            temperature=0.0,
            max_tokens=512,
            timeout_s=60.0,
        )
        judge_output = await client.chat([("user", judge_prompt)])

        result = parse_judge_output(judge_output, rubric)
        result.judge_type = judge_type
        return result

    except Exception as e:
        logger.warning("Judge call failed (%s), using heuristic fallback: %s", judge_type, e)
        result = _heuristic_fallback(model_output, rubric)
        result.judge_type = "deterministic"
        return result
