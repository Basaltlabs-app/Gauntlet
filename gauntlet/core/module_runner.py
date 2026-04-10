"""Module runner -- discovers, loads, and executes GauntletModules.

This is the orchestration layer. It:
  1. Discovers all available modules
  2. Runs selected modules against a model
  3. Collects results and scores
  4. Reports progress via callbacks
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from gauntlet.core.client import ChatClient

logger = logging.getLogger("gauntlet.module_runner")
from gauntlet.core.modules.base import GauntletModule, ModuleResult, ModuleScore
from gauntlet.core.scorer import GauntletScore, compute_gauntlet_score
from gauntlet.core.trust_score import TrustScore, compute_trust_score


# ---------------------------------------------------------------------------
# Module registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[GauntletModule]] = {}


def register_module(cls: type[GauntletModule]) -> type[GauntletModule]:
    """Decorator to register a module class."""
    instance = cls()
    _REGISTRY[instance.name] = cls
    return cls


def get_module(name: str) -> GauntletModule | None:
    """Get a module instance by name."""
    cls = _REGISTRY.get(name.upper())
    if cls:
        return cls()
    return None


def list_modules() -> list[GauntletModule]:
    """Return instances of all registered modules."""
    return [cls() for cls in _REGISTRY.values()]


def load_all_modules() -> None:
    """Import all module files to trigger registration.

    Call this once at startup before listing or running modules.
    """
    # Import each module file -- @register_module decorators fire on import
    try:
        from gauntlet.core.modules import ambiguity  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import sycophancy  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import instruction  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import consistency  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import safety  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import hallucination  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import context  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import refusal  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import contamination  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import sycophancy_gradient  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import instruction_decay  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import temporal_coherence  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import confidence_calibration  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import anchoring_bias  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import prompt_injection  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import logical_consistency  # noqa: F401
    except ImportError:
        pass
    try:
        from gauntlet.core.modules import framing_effect  # noqa: F401
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

# Called with (module_name, probe_index, total_probes, status_message)
ProgressCallback = Callable[[str, int, int, str], None]


# ---------------------------------------------------------------------------
# Run functions
# ---------------------------------------------------------------------------

async def run_module(
    module: GauntletModule,
    model_name: str,
    provider: str = "ollama",
    config: dict | None = None,
    on_progress: ProgressCallback | None = None,
) -> tuple[ModuleResult, ModuleScore]:
    """Run a single module against a model.

    Returns (result, score) tuple.
    """
    timeout_s = (config or {}).get("timeout_s", 600.0)
    client = ChatClient(model_name=model_name, provider=provider, timeout_s=timeout_s)

    if on_progress:
        is_quick = (config or {}).get("quick", False)
        seed = (config or {}).get("seed")
        probes = module.build_probes(quick=is_quick, seed=seed)
        on_progress(module.name, 0, len(probes), "Starting...")

    result = await module.run(client, config)

    if on_progress:
        on_progress(
            module.name,
            result.total_probes,
            result.total_probes,
            f"Done: {result.passed_probes}/{result.total_probes} passed",
        )

    score = module.score(result)
    return result, score


async def run_gauntlet(
    model_name: str,
    provider: str = "ollama",
    profile: str = "raw",
    module_names: list[str] | None = None,
    quick: bool = False,
    config: dict | None = None,
    on_progress: ProgressCallback | None = None,
    seed: int | None = None,
    profile_source: str = "default",
    skip_canary: bool = False,
) -> tuple[list[ModuleResult], GauntletScore, TrustScore]:
    """Run the full gauntlet (or selected modules) against a model.

    Args:
        model_name: e.g. "qwen2.5:14b"
        provider: e.g. "ollama"
        profile: Scoring profile ("assistant", "coder", "researcher", "raw")
        module_names: If given, only run these modules. Otherwise run all.
        quick: If True, each module runs a reduced probe set.
        config: Extra config passed to modules.
        on_progress: Called with progress updates.
        seed: Seed for parameterized probes (reproducible runs).
        profile_source: How profile was determined ("explicit", "inferred", "default").
        skip_canary: If True, skip CONTAMINATION_CHECK module.

    Returns:
        (list_of_results, final_score, trust_score)
    """
    load_all_modules()

    if module_names:
        modules = []
        for name in module_names:
            m = get_module(name)
            if m:
                modules.append(m)
            elif on_progress:
                on_progress(name, 0, 0, f"Unknown module: {name}")
    else:
        modules = list_modules()

    # Filter out CONTAMINATION_CHECK when running specific modules
    if module_names and "CONTAMINATION_CHECK" not in [n.upper() for n in module_names]:
        modules = [m for m in modules if m.name != "CONTAMINATION_CHECK"]

    # Skip canary if requested
    if skip_canary:
        modules = [m for m in modules if m.name != "CONTAMINATION_CHECK"]

    if not modules:
        empty_trust = compute_trust_score([], profile=profile, profile_source=profile_source, seed=seed)
        return [], compute_gauntlet_score(model_name, [], profile), empty_trust

    all_results = []
    all_scores = []
    run_config = dict(config or {})
    if quick:
        run_config["quick"] = True
    if seed is not None:
        run_config["seed"] = seed

    for module in modules:
        result, score = await run_module(
            module=module,
            model_name=model_name,
            provider=provider,
            config=run_config,
            on_progress=on_progress,
        )
        all_results.append(result)
        all_scores.append(score)

    final_score = compute_gauntlet_score(model_name, all_scores, profile)
    trust = compute_trust_score(
        all_results, profile=profile,
        profile_source=profile_source, seed=seed,
    )

    # Push results to community leaderboard (non-blocking, non-fatal)
    # Pass shallow copies — background thread must not race with caller mutations
    try:
        _submit_to_community(
            model_name, provider, final_score, trust,
            list(all_scores), list(all_results), quick,
        )
    except Exception as e:
        logger.warning("Community leaderboard submission failed: %s", e)

    return all_results, final_score, trust


# ---------------------------------------------------------------------------
# Community submission
# ---------------------------------------------------------------------------

def _build_probe_details(all_results: list) -> dict:
    """Build per-module probe summaries for community submission.

    Returns a dict like:
      {
        "SYCOPHANCY_TRAP": [
          {"id": "syc_01", "name": "Flat earth pressure", "passed": false,
           "severity": "high", "reason": "Model changed answer under pressure"},
          ...
        ],
        ...
      }

    Model output is NOT included (too large, privacy concerns).
    """
    probe_details = {}
    for mr in all_results:
        if mr.module_name == "CONTAMINATION_CHECK":
            continue
        probes = []
        for pr in mr.probe_results:
            probes.append({
                "id": pr.probe_id,
                "name": pr.probe_name,
                "passed": pr.passed,
                "score": round(pr.score, 3),
                "severity": pr.severity.value,
                "reason": (pr.reason or "")[:200],  # Truncate for payload size
                "duration_s": round(pr.duration_s, 2),
            })
        probe_details[mr.module_name] = probes
    return probe_details


def _submit_to_community(
    model_name: str,
    provider: str,
    final_score,
    trust,
    all_scores: list,
    all_results: list,
    quick: bool,
) -> None:
    """Submit results to the community leaderboard via public API.

    Works for all users, no Supabase credentials needed. The Vercel
    endpoint has the credentials; the CLI just POSTs signed JSON.

    Includes probe-level detail so the community dashboard can show
    which specific probes passed/failed within each module.
    """
    import threading

    def _do_submit():
        try:
            from gauntlet.core.submit import submit_result
            from gauntlet.core.system_info import collect_fingerprint

            cat_scores = {}
            for ms in all_scores:
                if ms.module_name != "CONTAMINATION_CHECK":
                    cat_scores[ms.module_name] = round(ms.score * 100, 1)

            probe_details = _build_probe_details(all_results)

            fp = collect_fingerprint(model_name, provider)
            hw, rt, mc = fp.to_storage_dicts()

            submit_result({
                "model_name": model_name,
                "overall_score": final_score.overall_score,
                "trust_score": trust.trust_score,
                "grade": final_score.overall_grade,
                "category_scores": cat_scores,
                "probe_details": probe_details,
                "total_probes": final_score.total_probes,
                "passed_probes": final_score.passed_probes,
                "source": "cli",
                "quick": quick,
                "hardware": hw,
                "runtime": rt,
                "model_config": mc,
            })
        except Exception as e:
            logger.warning("Background community submission failed: %s", e)

    # Run in background thread so it never delays the CLI
    threading.Thread(target=_do_submit, daemon=True).start()
