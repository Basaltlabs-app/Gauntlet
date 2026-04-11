"""Auto-judge system -- uses a model to score all outputs."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Optional

from gauntlet.core.config import resolve_model
from gauntlet.core.metrics import ComparisonResult, ModelMetrics
from gauntlet.core.providers.factory import create_provider

logger = logging.getLogger("gauntlet.judge")

if TYPE_CHECKING:
    from gauntlet.core.prompt_classifier import PromptClassification


# ---------------------------------------------------------------------------
# Generic judge prompt (backward-compatible default)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Domain-specific evaluation criteria
# ---------------------------------------------------------------------------

EVALUATION_CRITERIA: dict[str, dict] = {
    "database": {
        "label": "Database & Schema",
        "dimensions": [
            ("Schema Design", "Evaluate table structure, normalization, appropriate data types, indexing strategy, and relationship modeling"),
            ("Security", "Evaluate RLS policies, auth integration, permission boundaries, and SQL injection prevention"),
            ("Query Correctness", "Evaluate SQL or ORM queries for correctness, efficiency, proper joins, and edge case handling"),
            ("API Accuracy", "Verify that SDK methods and API calls actually exist and are used correctly. Flag any hallucinated or deprecated methods"),
        ],
        "watch_for": "hallucinated API methods that don't exist, missing RLS policies on tables with user data, incorrect foreign key relationships, SQL injection vulnerabilities, wrong column types",
    },
    "auth_security": {
        "label": "Authentication & Security",
        "dimensions": [
            ("Auth Flow", "Evaluate login/signup/session flows for correctness and completeness"),
            ("Security Practices", "Check for proper token handling, CSRF protection, secure cookie settings, password hashing"),
            ("Edge Cases", "Check for account recovery, session expiry, rate limiting, MFA handling"),
            ("API Accuracy", "Verify that auth SDK methods actually exist and are used correctly. Flag any hallucinated methods"),
        ],
        "watch_for": "hardcoded secrets, missing CSRF protection, hallucinated auth SDK methods, insecure token storage in localStorage, missing httpOnly flags",
    },
    "apps_script": {
        "label": "Google Apps Script",
        "dimensions": [
            ("API Usage", "Correct use of Google Apps Script services (SpreadsheetApp, DocumentApp, etc.) and their methods"),
            ("Quota Awareness", "Handling of execution time limits (6min/30min), URL fetch quotas, trigger limitations"),
            ("Trigger Patterns", "Correct use of simple triggers (onEdit, onOpen) vs installable triggers, event object handling"),
            ("Error Handling", "Proper try/catch patterns, UrlFetchApp error handling, Lock Service for concurrent access"),
        ],
        "watch_for": "deprecated GAS methods, quota-busting patterns like unnecessary getRange calls in loops, missing error handling for external API calls, wrong trigger event properties",
    },
    "frontend": {
        "label": "Frontend & UI",
        "dimensions": [
            ("Component Design", "Evaluate component structure, props design, state management, and reusability"),
            ("Styling", "Evaluate CSS/Tailwind usage, responsive design, accessibility, and visual consistency"),
            ("Interactivity", "Evaluate event handling, form validation, loading states, and error boundaries"),
            ("Best Practices", "Check for proper hooks usage, performance patterns (memoization, lazy loading), and framework conventions"),
        ],
        "watch_for": "incorrect hook dependencies, missing key props on lists, accessibility violations (missing alt text, no ARIA labels), non-responsive layouts",
    },
    "backend_api": {
        "label": "Backend & API",
        "dimensions": [
            ("API Design", "Evaluate endpoint structure, HTTP methods, status codes, and RESTful conventions"),
            ("Validation", "Check input validation, error responses, and boundary handling"),
            ("Security", "Evaluate authentication middleware, rate limiting, CORS configuration, and injection prevention"),
            ("Architecture", "Evaluate code organization, separation of concerns, and middleware patterns"),
        ],
        "watch_for": "missing input validation, wrong HTTP status codes, SQL injection via string concatenation, missing auth middleware on protected routes",
    },
    "devops": {
        "label": "DevOps & Infrastructure",
        "dimensions": [
            ("Configuration", "Evaluate Dockerfile/compose/k8s config correctness, multi-stage builds, security best practices"),
            ("Pipeline Design", "Evaluate CI/CD pipeline structure, caching, parallelization, and failure handling"),
            ("Security", "Check for secrets management, minimal base images, non-root users, network policies"),
            ("Reliability", "Evaluate health checks, restart policies, resource limits, and rollback strategies"),
        ],
        "watch_for": "running as root in containers, hardcoded secrets in CI config, missing health checks, oversized Docker images, no resource limits",
    },
    "data_analysis": {
        "label": "Data Analysis",
        "dimensions": [
            ("Data Handling", "Evaluate data loading, cleaning, type handling, and missing value treatment"),
            ("Analysis Logic", "Evaluate correctness of statistical methods, aggregations, grouping, and transformations"),
            ("Visualization", "Evaluate chart type selection, labeling, formatting, and clarity of visual output"),
            ("Code Efficiency", "Evaluate vectorized operations vs loops, memory usage, and pandas/numpy best practices"),
        ],
        "watch_for": "incorrect statistical methods for the data type, axis confusion in pandas, missing data type conversions, misleading visualizations",
    },
    "writing_content": {
        "label": "Writing & Content",
        "dimensions": [
            ("Structure", "Evaluate organization, flow, headings, transitions, and logical progression"),
            ("Tone & Voice", "Evaluate consistency of tone, audience appropriateness, and brand voice alignment"),
            ("Substance", "Evaluate depth of content, supporting details, and value to the reader"),
            ("Engagement", "Evaluate hooks, readability, calls to action, and reader retention techniques"),
        ],
        "watch_for": "inconsistent tone shifts, generic filler content, missing calls to action, walls of text without formatting",
    },
}


def _build_judge_system_prompt(
    classification: Optional["PromptClassification"] = None,
) -> str:
    """Build a judge system prompt, domain-specific when possible."""
    if classification is None or classification.subcategory is None:
        return JUDGE_SYSTEM_PROMPT

    criteria = EVALUATION_CRITERIA.get(classification.subcategory)
    if criteria is None:
        return JUDGE_SYSTEM_PROMPT

    # Build domain-specific prompt
    dims_text = "\n".join(
        f'{i}. **{name}** (1-10): {desc}'
        for i, (name, desc) in enumerate(criteria["dimensions"], 1)
    )

    dim_keys = ", ".join(
        f'"{name}"' for name, _ in criteria["dimensions"]
    )

    return f"""You are an expert judge evaluating AI model outputs for a {criteria['label']} task. Score each response on these domain-specific dimensions:

{dims_text}

WATCH FOR these common issues and flag them in specific_issues:
{criteria['watch_for']}

Respond ONLY with valid JSON in this exact format:
{{
  "results": [
    {{
      "model": "<model_name>",
      "dimensions": {{
        {", ".join(f'"{name}": {{"score": "<1-10>", "note": "<brief note>"}}' for name, _ in criteria["dimensions"])}
      }},
      "overall": <1-10>,
      "reasoning": "<brief explanation>",
      "specific_issues": ["<concrete issue found>", "...or empty list if none"]
    }}
  ],
  "winner": "<model_name>"
}}"""


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


def _parse_judge_response(
    text: str,
    models: list[ModelMetrics],
    is_domain_specific: bool = False,
) -> dict:
    """Parse the judge's JSON response, handling common formatting issues.

    Supports both generic format (correctness/completeness/clarity/code_quality)
    and domain-specific format (dimensions dict with named scores).
    """
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
    except json.JSONDecodeError as e:
        # Fallback: return equal scores
        logger.warning("Failed to parse judge JSON response: %s", e)
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
                    "specific_issues": [],
                }
                for name in model_names
            ],
            "winner": model_names[0] if model_names else None,
        }

    # Normalize domain-specific format into flat quality_scores for backward compat
    if is_domain_specific:
        for r in data.get("results", []):
            dims = r.get("dimensions", {})
            if dims and isinstance(dims, dict):
                # Flatten dimensions into top-level keys for quality_scores
                for dim_name, dim_data in dims.items():
                    if isinstance(dim_data, dict):
                        r[dim_name] = dim_data.get("score", 5)
                    elif isinstance(dim_data, (int, float)):
                        r[dim_name] = dim_data
            # Ensure specific_issues exists
            if "specific_issues" not in r:
                r["specific_issues"] = []

    return data


async def judge_comparison(
    comparison: ComparisonResult,
    judge_model: str = "auto",
    classification: Optional["PromptClassification"] = None,
) -> ComparisonResult:
    """Score all model outputs using a judge model.

    Args:
        comparison: The comparison result to judge
        judge_model: Model spec for the judge. "auto" picks the best available.
        classification: Optional prompt classification for domain-specific evaluation.

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
    system_prompt = _build_judge_system_prompt(classification)
    is_domain_specific = (
        classification is not None
        and classification.subcategory is not None
        and classification.subcategory in EVALUATION_CRITERIA
    )

    # Generate judge response with timeout and token limit
    import time
    output_parts = []
    token_count = 0
    start = time.perf_counter()
    async for chunk in provider.stream_generate(
        model=model_name,
        prompt=judge_prompt,
        system=system_prompt,
    ):
        output_parts.append(chunk.text)
        token_count += 1
        if chunk.done:
            break
        # Hard limits to prevent hanging
        if token_count >= 2000:
            break
        if time.perf_counter() - start > 45:
            break

    judge_text = "".join(output_parts)
    parsed = _parse_judge_response(judge_text, valid_models, is_domain_specific)

    # Apply scores to metrics
    results_by_model = {}
    for r in parsed.get("results", []):
        results_by_model[r.get("model", "")] = r

    if is_domain_specific:
        criteria = EVALUATION_CRITERIA[classification.subcategory]
        dim_names = [name for name, _ in criteria["dimensions"]]

        for m in comparison.models:
            scores = results_by_model.get(m.model, {})
            if scores:
                m.quality_scores = {}
                for dim_name in dim_names:
                    val = scores.get(dim_name, 5)
                    if isinstance(val, str):
                        try:
                            val = float(val)
                        except ValueError:
                            val = 5
                    m.quality_scores[dim_name] = val
                m.overall_score = scores.get("overall", 5)
                m.specific_issues = scores.get("specific_issues", [])
    else:
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
                m.specific_issues = scores.get("specific_issues", [])

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
            available.sort(key=lambda x: x.get("size", 0) or 0)  # smallest first — judge doesn't need to be large
            for m in available:
                name = m["name"]
                # Skip models that are being compared
                if name not in compared_models and name.split(":")[0] not in compared_models:
                    return name
    except Exception as e:
        logger.warning("Failed to auto-select judge model: %s", e)

    # Fallback: use the first compared model as judge (not ideal but works)
    return models[0].model if models else "llama3.2"
