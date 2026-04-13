"""Persistent benchmark result storage.

Saves benchmark runs to ~/.gauntlet/benchmarks/ as timestamped JSON files.
Provides listing, loading, and summary functions for the dashboard.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gauntlet.core.config import ensure_gauntlet_dir


BENCHMARKS_DIR = ensure_gauntlet_dir() / "benchmarks"


def _ensure_dir() -> Path:
    BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    return BENCHMARKS_DIR


def save_benchmark_run(
    results: list[dict],
    quick: bool = False,
    stopped: bool = False,
) -> str:
    """Save a benchmark run to disk.

    Args:
        results: List of BenchmarkSuiteResult.to_dict() dicts.
        quick: Whether the quick suite was used.
        stopped: Whether the run was cancelled early.

    Returns:
        The run ID (filename stem).
    """
    _ensure_dir()
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d_%H%M%S")

    models = [r["model"] for r in results]

    record = {
        "run_id": run_id,
        "timestamp": now.isoformat(),
        "quick": quick,
        "stopped": stopped,
        "models": models,
        "results": results,
    }

    path = BENCHMARKS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(record, indent=2))
    return run_id


def list_benchmark_runs(limit: int = 50) -> list[dict]:
    """List recent benchmark runs (most recent first).

    Returns lightweight summaries without full test details.
    """
    _ensure_dir()
    files = sorted(BENCHMARKS_DIR.glob("*.json"), reverse=True)

    runs = []
    for f in files[:limit]:
        try:
            data = json.loads(f.read_text())
            runs.append({
                "run_id": data.get("run_id", f.stem),
                "timestamp": data.get("timestamp"),
                "quick": data.get("quick", False),
                "stopped": data.get("stopped", False),
                "models": data.get("models", []),
                "scores": {
                    r["model"]: r["overall_score"]
                    for r in data.get("results", [])
                },
            })
        except (json.JSONDecodeError, KeyError):
            continue

    return runs


def load_benchmark_run(run_id: str) -> Optional[dict]:
    """Load a specific benchmark run by its ID."""
    path = BENCHMARKS_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, KeyError):
        return None


def get_latest_benchmark() -> Optional[dict]:
    """Load the most recent benchmark run."""
    _ensure_dir()
    files = sorted(BENCHMARKS_DIR.glob("*.json"), reverse=True)
    if not files:
        return None
    try:
        return json.loads(files[0].read_text())
    except (json.JSONDecodeError, KeyError):
        return None


def get_model_benchmark_history(model: str, limit: int = 20) -> list[dict]:
    """Get benchmark history for a specific model across runs.

    Returns list of {run_id, timestamp, overall_score, category_scores}.
    """
    _ensure_dir()
    files = sorted(BENCHMARKS_DIR.glob("*.json"), reverse=True)
    history = []

    for f in files:
        if len(history) >= limit:
            break
        try:
            data = json.loads(f.read_text())
            for r in data.get("results", []):
                if r["model"] == model:
                    history.append({
                        "run_id": data.get("run_id", f.stem),
                        "timestamp": data.get("timestamp"),
                        "overall_score": r["overall_score"],
                        "total_passed": r["total_passed"],
                        "total_tests": r["total_tests"],
                        "category_scores": r.get("category_scores", {}),
                    })
        except (json.JSONDecodeError, KeyError):
            continue

    return history


# ---------------------------------------------------------------------------
# Health check storage (separate from benchmark history)
# ---------------------------------------------------------------------------

GAUNTLET_DIR = ensure_gauntlet_dir()
HEALTH_DIR = GAUNTLET_DIR / "health"


def _sanitize_model_name(model: str) -> str:
    """Sanitize model name for filesystem use."""
    return model.replace(":", "_").replace("/", "_").replace("\\", "_")


def save_health_check(result: dict, model: str) -> str:
    """Save a health check result to disk.

    Stores in ~/.gauntlet/health/{model_name}/{timestamp}.json
    Returns the run_id (timestamp string).
    """
    safe_name = _sanitize_model_name(model)
    model_dir = HEALTH_DIR / safe_name
    model_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%d_%H%M%S")

    record = {
        "run_id": run_id,
        "timestamp": now.isoformat(),
        "model": model,
        **result,
    }

    path = model_dir / f"{run_id}.json"
    path.write_text(json.dumps(record, indent=2))
    return run_id


def get_health_history(model: str, limit: int = 20) -> list[dict]:
    """Load recent health check results for a model.

    Returns list of dicts sorted by timestamp descending.
    """
    safe_name = _sanitize_model_name(model)
    model_dir = HEALTH_DIR / safe_name

    if not model_dir.exists():
        return []

    files = sorted(model_dir.glob("*.json"), reverse=True)
    history = []

    for f in files[:limit]:
        try:
            data = json.loads(f.read_text())
            history.append(data)
        except (json.JSONDecodeError, KeyError):
            continue

    return history


def get_latest_health(model: str) -> dict | None:
    """Load the most recent health check result for a model."""
    history = get_health_history(model, limit=1)
    return history[0] if history else None
