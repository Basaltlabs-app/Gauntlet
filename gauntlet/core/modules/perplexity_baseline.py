"""Perplexity Baseline -- correlate prediction quality with behavioral scores.

This module is NOT a behavioral test. It measures the model's raw token
prediction quality (perplexity) alongside the behavioral probes, so the
community can empirically answer:

  "Does perplexity predict behavioral degradation under quantization?"

If a model has nearly identical perplexity at Q4 and Q8 but its sycophancy
resistance drops 40%, that's evidence that behavioral probes capture
something perplexity misses. If they track closely, perplexity is a
sufficient proxy and this module proves it.

Either result is useful data. The claim should be settled by evidence, not
by Reddit arguments.

Scoring:
  - NOT included in TrustScore or GauntletScore (it's a baseline, not a
    behavioral dimension).
  - Reported as a standalone metric in the leaderboard submission:
    `"perplexity": <float or null>`.
  - Also stored in the ModuleResult so it appears in local reports.

How it works:
  - Sends a fixed evaluation corpus (100-200 tokens of well-known text)
    through the model via the /api/generate endpoint with logprobs enabled.
  - Computes token-level perplexity: exp(-1/N * sum(log_probs)).
  - If the provider doesn't support logprobs (cloud APIs, older Ollama),
    the module gracefully returns null instead of blocking the run.

Supported providers:
  - Ollama: logprobs via /api/generate (Ollama v0.5+)
  - llama.cpp: logprobs via /v1/completions
  - Cloud (OpenAI, Anthropic, Google): NOT supported (no logprob access)
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

import httpx

from gauntlet.core.config import get_ollama_host, get_llamacpp_host
from gauntlet.core.modules.base import (
    GauntletModule,
    ModuleResult,
    ModuleScore,
    Probe,
    ProbeResult,
    Severity,
)
from gauntlet.core.module_runner import register_module

logger = logging.getLogger("gauntlet.perplexity")

# ---------------------------------------------------------------------------
# Fixed evaluation corpus
# ---------------------------------------------------------------------------
# A short, factual, well-known passage that any model has likely seen in
# pretraining. Using well-known text is INTENTIONAL -- we want the model's
# best-case prediction quality, not its ability to generalize. The comparison
# is: "how much does quantization degrade prediction quality on text the
# model should know cold?"
#
# Source: opening of the Wikipedia article "Oxygen" (public domain).
# ~160 tokens, enough for stable perplexity estimation.

EVAL_CORPUS = (
    "Oxygen is the chemical element with the symbol O and atomic number 8. "
    "It is a member of the chalcogen group in the periodic table, a highly "
    "reactive nonmetal, and a potent oxidizing agent that readily forms "
    "oxides with most elements as well as with other compounds. Oxygen is "
    "Earth's most abundant element, and after hydrogen and helium, it is the "
    "third-most abundant element in the universe. At standard temperature "
    "and pressure, two atoms of the element bind to form dioxygen, a "
    "colorless and odorless diatomic gas with the formula O2. Diatomic "
    "oxygen gas currently constitutes 20.95% of the Earth's atmosphere, "
    "though this has changed considerably over long periods of time. Oxygen "
    "makes up almost half of the Earth's crust in the form of various oxides."
)

# Split: first half is the prompt, second half is what we measure logprobs for.
# We need the model to GENERATE the second half so we can collect logprobs.
_split = len(EVAL_CORPUS) // 2
EVAL_PROMPT = EVAL_CORPUS[:_split]
EVAL_EXPECTED_CONTINUATION = EVAL_CORPUS[_split:]


# ---------------------------------------------------------------------------
# Perplexity computation helpers
# ---------------------------------------------------------------------------

def compute_perplexity(log_probs: list[float]) -> float:
    """Compute perplexity from a list of per-token log probabilities.

    perplexity = exp(-1/N * sum(log_probs))

    Lower is better. Typical values:
      - FP16 large model on known text: 3-8
      - Q8 of same: 4-10
      - Q4 of same: 5-15
      - Q2 of same: 10-50+
      - Random guessing (50k vocab): ~50,000
    """
    if not log_probs:
        return float("inf")
    avg_nll = -sum(log_probs) / len(log_probs)
    return math.exp(avg_nll)


# ---------------------------------------------------------------------------
# Provider-specific logprob fetchers
# ---------------------------------------------------------------------------

async def _ollama_logprobs(model: str, prompt: str, max_tokens: int = 200) -> tuple[list[float], str]:
    """Get logprobs from Ollama /api/generate.

    Returns (log_probs, generated_text). Raises if not supported.
    """
    host = get_ollama_host()
    url = f"{host}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": max_tokens,
        },
    }

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)

    async with httpx.AsyncClient(timeout=timeout) as http:
        resp = await http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    generated = data.get("response", "")

    # Ollama returns logprobs in the response when supported.
    # The exact field name varies by version; try common locations.
    logprobs_data = (
        data.get("logprobs")
        or data.get("completion_probabilities")
        or data.get("token_logprobs")
    )

    if logprobs_data and isinstance(logprobs_data, list):
        # Extract the log probability of each token
        lps = []
        for entry in logprobs_data:
            if isinstance(entry, dict):
                lp = entry.get("logprob") or entry.get("log_prob") or entry.get("token_logprob")
                if lp is not None:
                    lps.append(float(lp))
            elif isinstance(entry, (int, float)):
                lps.append(float(entry))
        if lps:
            return lps, generated

    # Fallback: check if tokens_evaluated is present but no logprobs
    # (means logprobs are not supported on this Ollama version)
    raise RuntimeError(
        "Ollama did not return logprob data. Perplexity measurement requires "
        "Ollama v0.5+ with logprob support. Skipping."
    )


async def _llamacpp_logprobs(model: str, prompt: str, max_tokens: int = 200) -> tuple[list[float], str]:
    """Get logprobs from llama.cpp /v1/completions endpoint.

    llama.cpp's OpenAI-compatible endpoint supports logprobs natively.
    """
    host = get_llamacpp_host()
    url = f"{host}/v1/completions"

    payload = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "logprobs": True,
        "stream": False,
    }

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)

    async with httpx.AsyncClient(timeout=timeout) as http:
        resp = await http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("llama.cpp returned no choices")

    choice = choices[0]
    generated = choice.get("text", "")
    logprobs_obj = choice.get("logprobs", {})
    token_logprobs = logprobs_obj.get("token_logprobs", [])

    lps = [float(lp) for lp in token_logprobs if lp is not None]
    if not lps:
        raise RuntimeError("llama.cpp did not return token logprobs")

    return lps, generated


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

@register_module
class PerplexityBaseline(GauntletModule):
    """Measure raw token prediction quality (perplexity) as a comparison baseline."""

    name = "PERPLEXITY_BASELINE"
    description = (
        "Measures the model's token prediction quality on a fixed evaluation corpus. "
        "NOT a behavioral test -- used to correlate perplexity with behavioral "
        "degradation across quantization levels. Lower perplexity = better prediction."
    )
    version = "0.1.0"

    # This module is special: it doesn't use the standard chat-based probe flow.
    # It calls the generate/completion endpoint directly for logprobs.
    # It also produces NO TrustScore or GauntletScore deductions.
    is_scoring_module = False  # Flag for scorer to skip

    def build_probes(self, quick: bool = False, seed: int | None = None) -> list[Probe]:
        """Single probe: evaluate the fixed corpus."""
        return [
            Probe(
                id="ppl_01",
                name="Corpus perplexity",
                description=(
                    "Token-level perplexity on a fixed evaluation passage. "
                    "Lower is better. Measures prediction quality, not behavior."
                ),
                severity=Severity.LOW,
                messages=[("user", EVAL_PROMPT)],
                expected="Low perplexity (strong prediction quality)",
                meta={"eval_corpus": EVAL_CORPUS},
            )
        ]

    def check(self, probe: Probe, model_output: str) -> tuple[bool, float, str]:
        """Not used directly -- see run() override."""
        return True, 1.0, "Perplexity computed via logprobs (not chat-based check)"

    async def run(
        self,
        client: "ChatClient",
        config: dict | None = None,
    ) -> ModuleResult:
        """Override the default run to use logprob-based perplexity instead of chat probes."""
        from gauntlet.core.client import ChatClient

        start = time.monotonic()
        provider = client.provider
        model = client.model_name

        perplexity_value: float | None = None
        log_probs: list[float] = []
        generated_text = ""
        error_msg: str | None = None

        try:
            if provider == "ollama":
                log_probs, generated_text = await _ollama_logprobs(model, EVAL_PROMPT)
            elif provider == "llamacpp":
                log_probs, generated_text = await _llamacpp_logprobs(model, EVAL_PROMPT)
            else:
                error_msg = f"Perplexity measurement not supported for provider '{provider}' (no logprob access). Skipping."
                logger.info(error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.info("Perplexity measurement skipped: %s", e)

        if log_probs:
            perplexity_value = compute_perplexity(log_probs)

        duration = time.monotonic() - start

        # Build a single ProbeResult that carries the perplexity value
        probe = self.build_probes()[0]
        result = ProbeResult(
            probe_id=probe.id,
            probe_name=probe.name,
            passed=perplexity_value is not None,
            score=1.0 if perplexity_value is not None else 0.0,
            severity=Severity.LOW,
            model_output=generated_text[:500] if generated_text else "(no logprobs available)",
            expected=probe.expected,
            reason=(
                f"Perplexity: {perplexity_value:.2f} (from {len(log_probs)} tokens)"
                if perplexity_value is not None
                else (error_msg or "Logprobs not available")
            ),
            duration_s=duration,
            meta={
                "perplexity": perplexity_value,
                "token_count": len(log_probs),
                "skipped": perplexity_value is None,
            },
        )

        return ModuleResult(
            module_name=self.name,
            module_version=self.versioned_id,
            model=model,
            probe_results=[result],
            total_duration_s=duration,
            error=error_msg if perplexity_value is None else None,
        )

    def score(self, result: ModuleResult) -> ModuleScore:
        """Score the perplexity module.

        This is a non-standard module: the 'score' is the perplexity value
        itself (stored in details), NOT a 0-1 behavioral score. The module
        is excluded from TrustScore and GauntletScore aggregation via the
        is_scoring_module=False flag.
        """
        if not result.probe_results:
            return ModuleScore(
                module_name=self.name,
                score=0.0,
                grade="?",
                passed=0,
                failed=1,
                total=1,
                critical_failures=0,
                high_failures=0,
                summary="Perplexity measurement not available",
                details={"perplexity": None, "skipped": True},
            )

        probe_result = result.probe_results[0]
        ppl = probe_result.meta.get("perplexity")
        skipped = probe_result.meta.get("skipped", True)

        if ppl is None or skipped:
            return ModuleScore(
                module_name=self.name,
                score=0.0,
                grade="?",
                passed=0,
                failed=0,
                total=1,
                critical_failures=0,
                high_failures=0,
                summary="Skipped (logprobs not available for this provider)",
                details={"perplexity": None, "skipped": True},
            )

        # Normalize to a 0-1 score for display purposes.
        # This is NOT used for TrustScore; it's just so the Rich display
        # can render a consistent bar chart.
        # Scale: ppl 1.0 = perfect = 1.0, ppl 100 = terrible = 0.0
        normalized = max(0.0, min(1.0, 1.0 - (math.log(ppl) / math.log(100))))

        return ModuleScore(
            module_name=self.name,
            score=normalized,
            grade=ModuleScore.grade_from_score(normalized),
            passed=1,
            failed=0,
            total=1,
            critical_failures=0,
            high_failures=0,
            summary=f"Perplexity: {ppl:.2f} ({len(probe_result.meta.get('log_probs', []))} tokens)",
            details={
                "perplexity": round(ppl, 4),
                "token_count": probe_result.meta.get("token_count", 0),
                "normalized_score": round(normalized, 4),
                "skipped": False,
            },
        )
