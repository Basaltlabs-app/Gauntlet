"""Core runner -- executes prompts against multiple models in parallel."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator, Callable, Optional

from gauntlet.core.config import resolve_model
from gauntlet.core.metrics import ComparisonResult, ModelMetrics
from gauntlet.core.providers.factory import create_provider


# Callback type for streaming progress updates
# (model_name, token_text, metrics_snapshot)
StreamCallback = Callable[[str, str, ModelMetrics], None]


async def run_single_model(
    model_spec: str,
    prompt: str,
    system: Optional[str] = None,
    image_path: Optional[str] = None,
    on_token: Optional[StreamCallback] = None,
) -> ModelMetrics:
    """Run a single model and collect metrics.

    Args:
        model_spec: Model specifier (e.g. "gemma4", "openai:gpt-4o")
        prompt: The prompt to send
        system: Optional system prompt
        image_path: Optional image for multimodal models
        on_token: Optional callback fired for each token

    Returns:
        ModelMetrics with all performance data and generated output
    """
    config = resolve_model(model_spec)
    provider, model_name = create_provider(config)

    metrics = ModelMetrics(
        model=model_name,
        provider=config.provider,
    )

    metrics.start()
    last_meta: dict = {}

    try:
        async for chunk in provider.stream_generate(
            model=model_name,
            prompt=prompt,
            system=system,
            image_path=image_path,
        ):
            if chunk.text:
                if metrics._first_token_time is None:
                    metrics.record_first_token()
                metrics.record_token(chunk.text)

                if on_token:
                    on_token(model_name, chunk.text, metrics)

            if chunk.meta:
                last_meta.update(chunk.meta)

            if chunk.done:
                break

    except Exception as e:
        metrics.output = f"[ERROR] {type(e).__name__}: {e}"

    metrics.finish(provider_meta=last_meta)
    return metrics


async def run_comparison(
    model_specs: list[str],
    prompt: str,
    system: Optional[str] = None,
    image_path: Optional[str] = None,
    on_token: Optional[StreamCallback] = None,
    sequential: bool = False,
) -> ComparisonResult:
    """Run the same prompt through multiple models.

    Args:
        model_specs: List of model specifiers
        prompt: The prompt to send to all models
        system: Optional system prompt
        image_path: Optional image path for multimodal
        on_token: Optional callback for streaming updates
        sequential: If True, run models one at a time (saves memory).
                    If False, run all in parallel (faster but uses more RAM).

    Returns:
        ComparisonResult with metrics for all models
    """
    if sequential:
        return await _run_sequential(model_specs, prompt, system, image_path, on_token)
    else:
        return await _run_parallel(model_specs, prompt, system, image_path, on_token)


async def _run_parallel(
    model_specs: list[str],
    prompt: str,
    system: Optional[str],
    image_path: Optional[str],
    on_token: Optional[StreamCallback],
) -> ComparisonResult:
    """Run all models in parallel (faster, more memory)."""
    tasks = [
        run_single_model(
            model_spec=spec,
            prompt=prompt,
            system=system,
            image_path=image_path,
            on_token=on_token,
        )
        for spec in model_specs
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    model_metrics = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            metrics = ModelMetrics(
                model=model_specs[i],
                provider="unknown",
                output=f"[ERROR] {type(result).__name__}: {result}",
            )
            model_metrics.append(metrics)
        else:
            model_metrics.append(result)

    return ComparisonResult(
        prompt=prompt,
        models=model_metrics,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


async def _run_sequential(
    model_specs: list[str],
    prompt: str,
    system: Optional[str],
    image_path: Optional[str],
    on_token: Optional[StreamCallback],
) -> ComparisonResult:
    """Run models one at a time. Each finishes and frees memory before the next starts.

    Better for low-RAM machines (8GB). Timing is still fair because each model
    gets the machine to itself with no contention.
    """
    model_metrics = []

    for spec in model_specs:
        try:
            metrics = await run_single_model(
                model_spec=spec,
                prompt=prompt,
                system=system,
                image_path=image_path,
                on_token=on_token,
            )
            model_metrics.append(metrics)
        except Exception as e:
            metrics = ModelMetrics(
                model=spec,
                provider="unknown",
                output=f"[ERROR] {type(e).__name__}: {e}",
            )
            model_metrics.append(metrics)

    return ComparisonResult(
        prompt=prompt,
        models=model_metrics,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


async def stream_comparison(
    model_specs: list[str],
    prompt: str,
    system: Optional[str] = None,
    image_path: Optional[str] = None,
) -> AsyncIterator[tuple[str, str, ModelMetrics | None]]:
    """Stream a comparison, yielding (event_type, model_name, data) tuples.

    Event types:
        "start"    - model generation started
        "token"    - a token was received
        "done"     - model generation complete
        "error"    - model encountered an error

    This is used by the WebSocket server for real-time dashboard updates.
    """
    queues: dict[str, asyncio.Queue] = {}
    tasks: list[asyncio.Task] = []

    async def _run_model(spec: str, queue: asyncio.Queue):
        config = resolve_model(spec)
        provider, model_name = create_provider(config)
        metrics = ModelMetrics(model=model_name, provider=config.provider)

        await queue.put(("start", model_name, metrics))
        metrics.start()
        last_meta: dict = {}

        try:
            async for chunk in provider.stream_generate(
                model=model_name, prompt=prompt, system=system, image_path=image_path
            ):
                if chunk.text:
                    if metrics._first_token_time is None:
                        metrics.record_first_token()
                    metrics.record_token(chunk.text)
                    await queue.put(("token", model_name, metrics))

                if chunk.meta:
                    last_meta.update(chunk.meta)

                if chunk.done:
                    break

            metrics.finish(provider_meta=last_meta)
            await queue.put(("done", model_name, metrics))

        except Exception as e:
            metrics.output = f"[ERROR] {type(e).__name__}: {e}"
            metrics.finish()
            await queue.put(("error", model_name, metrics))

        await queue.put(None)  # sentinel

    # Start all models
    merged_queue: asyncio.Queue = asyncio.Queue()
    for spec in model_specs:
        task = asyncio.create_task(_run_model(spec, merged_queue))
        tasks.append(task)

    finished = 0
    total = len(model_specs)

    while finished < total:
        item = await merged_queue.get()
        if item is None:
            finished += 1
            continue
        yield item

    # Ensure all tasks are cleaned up
    for task in tasks:
        if not task.done():
            task.cancel()
