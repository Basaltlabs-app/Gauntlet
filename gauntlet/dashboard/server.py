"""FastAPI dashboard backend with WebSocket streaming."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional, Callable

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from gauntlet.core.judge import judge_comparison
from gauntlet.core.leaderboard import Leaderboard
from gauntlet.core.metrics import ComparisonResult, ModelMetrics
from gauntlet.core.runner import stream_comparison, run_single_model
from gauntlet.core.config import resolve_model
from gauntlet.core.benchmarks import (
    run_benchmark_suite, get_suite_info, BenchmarkSuiteResult,
)
from gauntlet.core.benchmark_history import (
    save_benchmark_run, list_benchmark_runs, load_benchmark_run,
    get_latest_benchmark, get_model_benchmark_history,
)

FRONTEND_DIR = Path(__file__).parent / "frontend" / "dist"

app = FastAPI(title="Gauntlet Dashboard")


# ---------------------------------------------------------------------------
# Client tracking + auto-shutdown
# ---------------------------------------------------------------------------

_connected_clients: set[int] = set()
_client_counter: int = 0
_shutdown_task: Optional[asyncio.Task] = None
_server_ref: Optional[uvicorn.Server] = None
_auto_shutdown_delay: int = 15  # seconds to wait after last client disconnects
_on_client_change: Optional[Callable[[int], None]] = None  # TUI callback
_on_event: Optional[Callable[[str], None]] = None  # TUI event callback

def _notify_client_change():
    """Notify TUI of client count change."""
    if _on_client_change:
        _on_client_change(len(_connected_clients))

def _notify_event(msg: str):
    """Notify TUI of a server event."""
    if _on_event:
        _on_event(msg)

def _register_client() -> int:
    """Register a new WebSocket client. Returns client ID."""
    global _client_counter, _shutdown_task
    _client_counter += 1
    client_id = _client_counter
    _connected_clients.add(client_id)

    # Cancel any pending shutdown
    if _shutdown_task and not _shutdown_task.done():
        _shutdown_task.cancel()
        _shutdown_task = None
        _notify_event("Auto-shutdown cancelled (client reconnected)")

    _notify_client_change()
    _notify_event(f"Client #{client_id} connected ({len(_connected_clients)} total)")
    return client_id

def _unregister_client(client_id: int):
    """Unregister a WebSocket client. Starts auto-shutdown if none remain."""
    global _shutdown_task
    _connected_clients.discard(client_id)
    _notify_client_change()
    _notify_event(f"Client #{client_id} disconnected ({len(_connected_clients)} remaining)")

    if not _connected_clients and _server_ref:
        # All clients gone -- start countdown
        _notify_event(f"All clients disconnected. Shutting down in {_auto_shutdown_delay}s...")
        try:
            loop = asyncio.get_event_loop()
            _shutdown_task = loop.create_task(_auto_shutdown_countdown())
        except RuntimeError:
            pass

async def _auto_shutdown_countdown():
    """Wait, then shut down if no clients have reconnected."""
    try:
        await asyncio.sleep(_auto_shutdown_delay)
        if not _connected_clients and _server_ref:
            _notify_event("No clients reconnected. Shutting down server.")
            _server_ref.should_exit = True
    except asyncio.CancelledError:
        pass  # Client reconnected, shutdown cancelled


# ---------------------------------------------------------------------------
# Port management utilities
# ---------------------------------------------------------------------------

def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is currently in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _kill_port(port: int) -> bool:
    """Kill whatever process is using the given port. Returns True if killed."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split("\n")
        pids = [p.strip() for p in pids if p.strip()]

        if not pids:
            return False

        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass

        # Give processes a moment to exit gracefully
        import time
        time.sleep(0.5)

        # Force kill any that survived
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass

        return True
    except Exception:
        return False


def ensure_port_available(port: int, host: str = "127.0.0.1") -> None:
    """Ensure the port is available, killing any stale process if needed.

    This is the failsafe that prevents 'Address already in use' errors.
    It handles:
      - Zombie gauntlet processes from Ctrl+C during streaming
      - Stale sockets in TIME_WAIT state (via SO_REUSEADDR)
      - Any other process squatting on the port
    """
    if not _is_port_in_use(port, host):
        return

    # Check if it's a previous gauntlet instance
    try:
        import httpx
        resp = httpx.get(f"http://{host}:{port}/api/health", timeout=2)
        is_gauntlet = resp.json().get("status") == "ok"
    except Exception:
        is_gauntlet = False

    if is_gauntlet:
        print(f"[gauntlet] Found stale Gauntlet server on port {port}, shutting it down...")
    else:
        print(f"[gauntlet] Port {port} is in use by another process, clearing...")

    killed = _kill_port(port)

    # Wait for port to actually free up (TIME_WAIT can linger)
    import time
    for _ in range(10):
        if not _is_port_in_use(port, host):
            if killed:
                print(f"[gauntlet] Port {port} cleared successfully.")
            return
        time.sleep(0.3)

    # Last resort: the port might be in TIME_WAIT but SO_REUSEADDR will handle it
    print(f"[gauntlet] Port {port} still in TIME_WAIT, will attempt bind with SO_REUSEADDR.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# State for the current comparison
_comparison_state: dict = {
    "model_specs": [],
    "prompt": "",
    "image_path": None,
    "judge_model": "auto",
    "no_judge": False,
    "system": None,
    "result": None,
    "leaderboard": None,
    "sequential": False,
}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/leaderboard")
async def get_leaderboard():
    lb = Leaderboard()
    return lb.to_dict()


@app.get("/api/config")
async def get_config():
    return {
        "model_specs": _comparison_state["model_specs"],
        "prompt": _comparison_state["prompt"],
    }


@app.get("/api/result")
async def get_result():
    if _comparison_state["result"]:
        return _comparison_state["result"].to_dict()
    return {"status": "pending"}


@app.get("/api/models")
async def get_models():
    """List all available models with memory fitness info."""
    from gauntlet.core.discover import (
        discover_ollama, discover_openai, discover_anthropic,
        discover_google, get_system_memory,
    )

    all_models = []
    for discover_fn in [discover_ollama, discover_openai, discover_anthropic, discover_google]:
        try:
            found = await discover_fn()
            all_models.extend(found)
        except Exception:
            pass

    mem = get_system_memory()

    return {
        "system": {
            "total_ram_gb": mem["total_gb"],
            "available_ram_gb": mem["available_gb"],
            "ram_percent_used": mem["percent"],
        },
        "models": [
            {
                "name": m.name,
                "provider": m.provider,
                "size_gb": m.size_gb,
                "parameter_size": m.parameter_size,
                "family": m.family,
                "multimodal": m.multimodal,
                "spec": m.spec,
                "fits_in_memory": m.fits_in_memory,
                "memory_warning": m.memory_warning,
            }
            for m in all_models
        ],
    }


@app.post("/api/run")
async def start_run(body: dict):
    """Start a comparison from the dashboard.

    Body: {"models": ["gemma4:e2b", "qwen3.5:4b"], "prompt": "...", "sequential": true}
    """
    models = body.get("models", [])
    prompt = body.get("prompt", "")
    sequential = body.get("sequential", True)

    if not models or not prompt:
        return {"error": "Need at least one model and a prompt"}

    # Update state so the WebSocket picks it up
    _comparison_state.update({
        "model_specs": models,
        "prompt": prompt,
        "sequential": sequential,
        "no_judge": body.get("no_judge", False),
        "judge_model": body.get("judge_model", "auto"),
        "system": body.get("system"),
        "image_path": None,
        "result": None,
    })

    return {"status": "started", "models": models, "prompt": prompt}


@app.post("/api/benchmark")
async def start_benchmark(body: dict):
    """Start a benchmark run from the dashboard (legacy blocking endpoint).

    Body: {"models": ["gemma4:e2b"], "quick": false}
    """
    from gauntlet.core.benchmarks import run_benchmark_comparison

    models = body.get("models", [])
    quick = body.get("quick", False)

    if not models:
        return {"error": "Need at least one model"}

    results = await run_benchmark_comparison(models, quick=quick)
    result_dicts = [r.to_dict() for r in results]
    run_id = save_benchmark_run(result_dicts, quick=quick)
    _update_leaderboard_from_benchmark(results)
    return {"results": result_dicts, "run_id": run_id}


@app.get("/api/benchmark/categories")
async def get_benchmark_categories():
    """Get available benchmark test categories for the UI."""
    from gauntlet.core.benchmarks import CATEGORIES, ALL_TESTS, QUICK_TESTS
    return {
        "categories": CATEGORIES,
        "total_tests": len(ALL_TESTS),
        "quick_tests": len(QUICK_TESTS),
    }


@app.get("/api/benchmark/suite")
async def get_benchmark_suite_info(quick: bool = False):
    """Return test manifest for the UI progress trail."""
    return {"tests": get_suite_info(quick)}


@app.get("/api/benchmark/history")
async def get_benchmark_history(limit: int = 50):
    """List recent benchmark runs."""
    return {"runs": list_benchmark_runs(limit=limit)}


@app.get("/api/benchmark/history/{run_id}")
async def get_benchmark_run(run_id: str):
    """Load a specific benchmark run."""
    data = load_benchmark_run(run_id)
    if not data:
        return {"error": "Run not found"}
    return data


@app.get("/api/benchmark/latest")
async def get_latest_benchmark_run():
    """Load the most recent benchmark run."""
    data = get_latest_benchmark()
    if not data:
        return {"results": None}
    return data


@app.get("/api/benchmark/model/{model}")
async def get_model_history(model: str, limit: int = 20):
    """Get benchmark history for a specific model."""
    return {"history": get_model_benchmark_history(model, limit=limit)}


# ---------------------------------------------------------------------------
# Benchmark streaming state
# ---------------------------------------------------------------------------
_benchmark_cancel: Optional[asyncio.Event] = None
_benchmark_task: Optional[asyncio.Task] = None


@app.post("/api/benchmark/stop")
async def stop_benchmark():
    """Cancel a running benchmark."""
    global _benchmark_cancel
    if _benchmark_cancel:
        _benchmark_cancel.set()
        return {"status": "stopping"}
    return {"status": "no_benchmark_running"}


def _update_leaderboard_from_benchmark(results: list[BenchmarkSuiteResult]):
    """Update leaderboard rankings from benchmark results.

    When multiple models are benchmarked, treat it like a comparison:
    the model with the higher overall score wins.
    """
    if len(results) < 2:
        return  # Need at least 2 models for a ranking

    lb = Leaderboard()

    # Sort by overall score descending
    sorted_results = sorted(results, key=lambda r: r.overall_score, reverse=True)

    # Pairwise updates: each pair gets a rating update
    for i in range(len(sorted_results)):
        for j in range(i + 1, len(sorted_results)):
            winner = sorted_results[i]
            loser = sorted_results[j]

            # Build a minimal ComparisonResult
            from gauntlet.core.metrics import ModelMetrics
            w_metrics = ModelMetrics(model=winner.model, provider="benchmark")
            w_metrics.overall_score = winner.overall_score * 10  # 0-10 scale
            l_metrics = ModelMetrics(model=loser.model, provider="benchmark")
            l_metrics.overall_score = loser.overall_score * 10

            result = ComparisonResult(
                prompt="benchmark",
                models=[w_metrics, l_metrics],
                winner=winner.model,
            )
            lb.update_from_comparison(result)


async def _run_benchmark_streaming(
    ws: WebSocket,
    models: list[str],
    quick: bool,
    cancel_event: asyncio.Event,
):
    """Run benchmark with per-test progress streamed over WebSocket.

    Events sent:
        benchmark_start  - {models, total_tests, suite_info}
        benchmark_model_start - {model, model_index, total_models}
        benchmark_test_start  - {model, test_name, test_index, total_tests, category}
        benchmark_test_done   - {model, test_name, test_index, passed, score_pct, duration_s, category, details}
        benchmark_model_done  - {model, model_result: {...}}
        benchmark_complete    - {results: [...]}
        benchmark_stopped     - {reason, partial_results}
    """
    suite_info = get_suite_info(quick)
    total_tests = len(suite_info)

    await ws.send_json({
        "type": "benchmark_start",
        "models": models,
        "total_tests": total_tests,
        "suite_info": suite_info,
    })

    all_results: list[BenchmarkSuiteResult] = []

    for mi, model_spec in enumerate(models):
        if cancel_event.is_set():
            break

        await ws.send_json({
            "type": "benchmark_model_start",
            "model": model_spec,
            "model_index": mi,
            "total_models": len(models),
        })

        # Use on_progress callback to stream per-test events
        current_test_idx = {"value": 0}

        def _on_progress(model, idx, total, test_name, _mi=mi):
            current_test_idx["value"] = idx - 1  # 0-based

        # Run suite with cancel support
        from gauntlet.core.benchmarks import QUICK_TESTS, ALL_TESTS, _TEST_CATEGORIES

        suite = QUICK_TESTS if quick else ALL_TESTS
        suite_result = BenchmarkSuiteResult(model=model_spec)

        for ti, test_fn in enumerate(suite):
            if cancel_event.is_set():
                break

            test_name = test_fn.__name__.replace("test_", "")
            cat = _TEST_CATEGORIES.get(test_fn.__name__, "unknown")

            # Notify test starting
            await ws.send_json({
                "type": "benchmark_test_start",
                "model": model_spec,
                "test_name": test_name,
                "test_index": ti,
                "total_tests": total_tests,
                "category": cat,
            })

            try:
                bench = await asyncio.wait_for(test_fn(model_spec), timeout=90.0)
                suite_result.results.append(bench)

                await ws.send_json({
                    "type": "benchmark_test_done",
                    "model": model_spec,
                    "test_name": bench.name,
                    "test_index": ti,
                    "passed": bench.passed,
                    "score_pct": round((bench.score / bench.max_score) * 100, 1),
                    "duration_s": round(bench.duration_s, 2) if bench.duration_s else None,
                    "category": bench.category,
                    "description": bench.description,
                })

            except asyncio.TimeoutError:
                from gauntlet.core.benchmarks import BenchmarkResult
                br = BenchmarkResult(
                    name=test_name, category="timeout",
                    description="Test timed out after 90s",
                    model=model_spec, score=0, max_score=1, passed=False,
                    details={"error": "timeout"}, duration_s=90.0,
                )
                suite_result.results.append(br)
                await ws.send_json({
                    "type": "benchmark_test_done",
                    "model": model_spec,
                    "test_name": test_name,
                    "test_index": ti,
                    "passed": False,
                    "score_pct": 0,
                    "duration_s": 90.0,
                    "category": "timeout",
                    "description": "Test timed out after 90s",
                })

            except Exception as e:
                from gauntlet.core.benchmarks import BenchmarkResult
                br = BenchmarkResult(
                    name=test_name, category="error",
                    description=str(e),
                    model=model_spec, score=0, max_score=1, passed=False,
                    details={"error": str(e)},
                )
                suite_result.results.append(br)
                await ws.send_json({
                    "type": "benchmark_test_done",
                    "model": model_spec,
                    "test_name": test_name,
                    "test_index": ti,
                    "passed": False,
                    "score_pct": 0,
                    "duration_s": None,
                    "category": "error",
                    "description": str(e),
                })

        suite_result.compute_scores()
        all_results.append(suite_result)

        await ws.send_json({
            "type": "benchmark_model_done",
            "model": model_spec,
            "model_result": suite_result.to_dict(),
        })

    # Persist results to disk
    result_dicts = [r.to_dict() for r in all_results]
    was_stopped = cancel_event.is_set()
    run_id = save_benchmark_run(result_dicts, quick=quick, stopped=was_stopped)

    if was_stopped:
        await ws.send_json({
            "type": "benchmark_stopped",
            "reason": "Cancelled by user",
            "partial_results": result_dicts,
            "run_id": run_id,
        })
    else:
        await ws.send_json({
            "type": "benchmark_complete",
            "results": result_dicts,
            "run_id": run_id,
        })

    # Update leaderboard with benchmark scores and send to client
    _update_leaderboard_from_benchmark(all_results)
    lb = Leaderboard()
    await ws.send_json({"type": "leaderboard", "data": lb.to_dict()})


async def _ws_command_loop(ws: WebSocket):
    """Interactive command loop — listens for client messages.

    Handles:
        {"action": "start_benchmark", "models": [...], "quick": false}
        {"action": "stop_benchmark"}
    """
    global _benchmark_cancel, _benchmark_task

    while True:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=30)
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "start_benchmark":
                models = msg.get("models", [])
                quick = msg.get("quick", False)
                if not models:
                    await ws.send_json({"type": "error", "message": "No models selected"})
                    continue

                # Cancel any previous benchmark
                if _benchmark_cancel:
                    _benchmark_cancel.set()
                if _benchmark_task and not _benchmark_task.done():
                    _benchmark_task.cancel()
                    try:
                        await _benchmark_task
                    except (asyncio.CancelledError, Exception):
                        pass

                _benchmark_cancel = asyncio.Event()
                _benchmark_task = asyncio.create_task(
                    _run_benchmark_streaming(ws, models, quick, _benchmark_cancel)
                )

            elif action == "stop_benchmark":
                if _benchmark_cancel:
                    _benchmark_cancel.set()
                    await ws.send_json({"type": "benchmark_stopping"})

        except asyncio.TimeoutError:
            try:
                await ws.send_json({"type": "ping"})
            except Exception:
                break
        except WebSocketDisconnect:
            break
        except json.JSONDecodeError:
            pass  # Ignore malformed messages
        except Exception:
            break

    # Clean up benchmark on disconnect
    if _benchmark_cancel:
        _benchmark_cancel.set()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket endpoint for real-time comparison streaming.

    Sends events:
        {"type": "config", "models": [...], "prompt": "..."}
        {"type": "start", "model": "gemma4"}
        {"type": "token", "model": "gemma4", "text": "...", "metrics": {...}}
        {"type": "done", "model": "gemma4", "metrics": {...}}
        {"type": "judging"}
        {"type": "result", "data": {...}}
        {"type": "leaderboard", "data": {...}}
    """
    await ws.accept()
    client_id = _register_client()

    try:
        # Send config
        await ws.send_json(
            {
                "type": "config",
                "models": _comparison_state["model_specs"],
                "prompt": _comparison_state["prompt"],
            }
        )

        # Always send leaderboard data
        lb = Leaderboard()
        await ws.send_json({"type": "leaderboard", "data": lb.to_dict()})

        # If no models configured, just keep connection alive (dashboard-only mode)
        if not _comparison_state["model_specs"]:
            await ws.send_json({"type": "idle", "message": "No comparison running."})
            await _ws_command_loop(ws)
            return

        # If we already have a result, send it immediately then enter interactive mode
        if _comparison_state["result"]:
            await ws.send_json(
                {
                    "type": "result",
                    "data": _comparison_state["result"].to_dict(),
                }
            )
            lb = Leaderboard()
            await ws.send_json({"type": "leaderboard", "data": lb.to_dict()})
            await _ws_command_loop(ws)
            return

        # Stream the comparison
        all_metrics = []
        is_seq = _comparison_state.get("sequential", False)

        if is_seq:
            # Sequential: run one model at a time, queue tokens for ordered sends
            for spec in _comparison_state["model_specs"]:
                cfg = resolve_model(spec)
                model_name = cfg.extra["model"]
                await ws.send_json({"type": "start", "model": model_name})

                token_queue = asyncio.Queue()

                def _on_token_sync(name, text, m, _q=token_queue):
                    _q.put_nowait({
                        "type": "token",
                        "model": name,
                        "text": m.output[-50:],
                        "total_text_length": len(m.output),
                        "metrics": {
                            "tokens": m._token_count,
                            "tokens_per_sec": round(m.tokens_per_sec, 1) if m.tokens_per_sec else None,
                            "ttft_ms": round(m.ttft_ms, 1) if m.ttft_ms else None,
                        },
                    })

                async def _drain_queue(q, done_event):
                    while not done_event.is_set() or not q.empty():
                        try:
                            msg = q.get_nowait()
                            await ws.send_json(msg)
                        except asyncio.QueueEmpty:
                            await asyncio.sleep(0.05)

                try:
                    done_event = asyncio.Event()
                    drain_task = asyncio.create_task(_drain_queue(token_queue, done_event))

                    metrics = await run_single_model(
                        model_spec=spec,
                        prompt=_comparison_state["prompt"],
                        system=_comparison_state.get("system"),
                        image_path=_comparison_state.get("image_path"),
                        on_token=_on_token_sync,
                    )

                    done_event.set()
                    await drain_task

                    all_metrics.append(metrics)
                    await ws.send_json({"type": "done", "model": model_name, "metrics": metrics.to_dict()})
                except Exception as e:
                    done_event.set()
                    m = ModelMetrics(model=model_name, provider=cfg.provider, output=f"[ERROR] {e}")
                    all_metrics.append(m)
                    await ws.send_json({"type": "error", "model": model_name, "metrics": m.to_dict()})
        else:
            # Parallel: stream all at once
            async for event_type, model_name, metrics in stream_comparison(
                model_specs=_comparison_state["model_specs"],
                prompt=_comparison_state["prompt"],
                system=_comparison_state.get("system"),
                image_path=_comparison_state.get("image_path"),
            ):
                if event_type == "start":
                    await ws.send_json({"type": "start", "model": model_name})
                elif event_type == "token":
                    await ws.send_json({
                        "type": "token",
                        "model": model_name,
                        "text": metrics.output[-50:],
                        "total_text_length": len(metrics.output),
                        "metrics": {
                            "tokens": metrics._token_count,
                            "tokens_per_sec": round(metrics.tokens_per_sec, 1) if metrics.tokens_per_sec else None,
                            "ttft_ms": round(metrics.ttft_ms, 1) if metrics.ttft_ms else None,
                        },
                    })
                elif event_type in ("done", "error"):
                    all_metrics.append(metrics)
                    await ws.send_json({
                        "type": "done" if event_type == "done" else "error",
                        "model": model_name,
                        "metrics": metrics.to_dict(),
                    })

        # Build comparison result
        result = ComparisonResult(
            prompt=_comparison_state["prompt"],
            models=all_metrics,
        )

        # Classify prompt for domain-aware evaluation
        from gauntlet.core.prompt_classifier import classify_prompt_detailed
        from gauntlet.core.recommendation import generate_recommendation
        from gauntlet.core.metrics import compute_composite_scores, weights_for_category

        classification = classify_prompt_detailed(_comparison_state["prompt"])

        # Judge
        has_quality = False
        if not _comparison_state["no_judge"] and len(all_metrics) > 1:
            await ws.send_json({"type": "judging"})
            result = await judge_comparison(
                result, judge_model=_comparison_state["judge_model"],
                classification=classification,
            )
            has_quality = True

        # Compute composite scores with category-specific weights
        category_weights = weights_for_category(classification.subcategory)
        result.scoring = compute_composite_scores(
            result, weights=category_weights, has_quality=has_quality,
        )
        result.winner = result.scoring.winner if result.scoring else None
        result.classification = classification
        result.recommendation = generate_recommendation(result)

        # Update leaderboard
        if len(all_metrics) > 1:
            lb = Leaderboard()
            lb.update_from_comparison(result)
            await ws.send_json({"type": "leaderboard", "data": lb.to_dict()})

        _comparison_state["result"] = result
        await ws.send_json({"type": "result", "data": result.to_dict()})

        # After comparison, enter interactive mode for benchmarks etc.
        await _ws_command_loop(ws)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        _unregister_client(client_id)


def _find_frontend_dist() -> Optional[Path]:
    """Find the frontend dist directory, checking multiple locations."""
    candidates = [
        Path(__file__).parent / "frontend" / "dist",
        Path(__file__).resolve().parent / "frontend" / "dist",
    ]
    for c in candidates:
        if c.exists() and (c / "index.html").exists():
            return c
    return None


_DIST = _find_frontend_dist()

if _DIST and (_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


@app.get("/")
async def serve_index():
    """Serve the dashboard index page."""
    dist = _find_frontend_dist()
    if dist:
        return FileResponse(str(dist / "index.html"))
    return HTMLResponse(
        "<h1>Gauntlet Dashboard</h1>"
        "<p>Frontend not built yet. Run:</p>"
        "<pre>cd gauntlet/dashboard/frontend && npm install && npm run build</pre>"
        "<p>WebSocket API is available at /ws</p>"
    )


async def start_server(
    model_specs: list[str],
    prompt: str,
    image_path: Optional[str] = None,
    judge_model: str = "auto",
    no_judge: bool = False,
    system: Optional[str] = None,
    sequential: bool = False,
    port: int = 7878,
    on_client_change: Optional[Callable[[int], None]] = None,
    on_event: Optional[Callable[[str], None]] = None,
    auto_shutdown: bool = True,
) -> None:
    """Start the dashboard server and open the browser.

    Includes automatic port cleanup: if port is already in use (from a
    previous crashed/killed gauntlet process), it will be freed automatically.

    Args:
        on_client_change: Called when WebSocket client count changes. Receives count.
        on_event: Called with event log messages for TUI display.
        auto_shutdown: If True, server shuts down when all browser clients disconnect.
    """
    global _server_ref, _on_client_change, _on_event, _auto_shutdown_delay

    # ---- FAILSAFE: clear stale processes on our port ----
    ensure_port_available(port)

    # Wire up TUI callbacks
    _on_client_change = on_client_change
    _on_event = on_event
    if not auto_shutdown:
        _auto_shutdown_delay = 999999  # effectively disabled

    _comparison_state.update(
        {
            "model_specs": model_specs,
            "prompt": prompt,
            "image_path": image_path,
            "judge_model": judge_model,
            "no_judge": no_judge,
            "system": system,
            "sequential": sequential,
            "result": None,
        }
    )

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        # Graceful shutdown timeout: don't hang forever waiting for
        # active WebSocket connections to drain. 3 seconds is plenty.
        timeout_graceful_shutdown=3,
    )
    server = uvicorn.Server(config)
    _server_ref = server  # Store for auto-shutdown access

    # Register signal handlers for clean shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_shutdown(server, s)))

    _notify_event(f"Server starting on http://127.0.0.1:{port}")

    # Open browser after a short delay
    async def _open_browser():
        await asyncio.sleep(1)
        webbrowser.open(f"http://127.0.0.1:{port}")
        _notify_event("Browser opened")

    try:
        await asyncio.gather(
            server.serve(),
            _open_browser(),
        )
    except (KeyboardInterrupt, SystemExit):
        pass  # Clean exit, uvicorn handles socket release
    finally:
        _server_ref = None
        _on_client_change = None
        _on_event = None


async def _shutdown(server: uvicorn.Server, sig: signal.Signals) -> None:
    """Graceful shutdown handler. Ensures the socket is released promptly."""
    server.should_exit = True
