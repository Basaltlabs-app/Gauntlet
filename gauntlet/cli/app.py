"""Gauntlet CLI - Typer-based command line interface."""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import typer
from rich.live import Live

from gauntlet.cli.display import (
    console,
    create_progress,
    get_model_color,
    print_comparing,
    print_discover,
    print_error,
    print_header,
    print_head_to_head,
    print_json_output,
    print_leaderboard,
    print_model_output,
    print_results,
    print_trust_report,
    update_progress,
)

app = typer.Typer(
    name="gauntlet",
    help="Behavioral reliability under pressure. Test how your LLM behaves -- not what it knows.",
    add_completion=False,
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    """Launch the interactive TUI when called with no arguments."""
    if ctx.invoked_subcommand is not None:
        return  # A subcommand like 'run', 'compare', etc. was given

    # Bare `gauntlet` -- launch the interactive TUI
    from gauntlet.cli.tui import GauntletApp
    tui = GauntletApp()
    tui.run()


# ---------------------------------------------------------------------------
# gauntlet run  -- behavioral reliability tests (the core of Gauntlet)
# ---------------------------------------------------------------------------

@app.command()
def run(
    model: list[str] = typer.Option(
        None, "--model", "-m",
        help="Model to test (e.g. ollama/qwen2.5:14b, lmstudio/llama-3.2-8b, openai/gpt-4o). Can specify multiple.",
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p",
        help="Scoring profile: assistant, coder, researcher, raw",
    ),
    module: Optional[str] = typer.Option(
        None, "--module",
        help="Run only this module (e.g. sycophancy, ambiguity)",
    ),
    quick: bool = typer.Option(
        False, "--quick", "-q",
        help="Run reduced probe set (faster)",
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Output format: json",
    ),
    timeout: int = typer.Option(
        600, "--timeout",
        help="Per-probe timeout in seconds (thinking models need 300-900s)",
    ),
    list_modules: bool = typer.Option(
        False, "--list-modules",
        help="List available test modules and exit",
    ),
    prompt: Optional[str] = typer.Option(
        None, "--prompt",
        help="User prompt for context-aware profile inference",
    ),
    seed: Optional[int] = typer.Option(
        None, "--seed",
        help="Seed for parameterized probes (reproducible runs)",
    ),
    report: bool = typer.Option(
        False, "--report",
        help="Generate HTML report file after run",
    ),
    tui: bool = typer.Option(
        False, "--tui",
        help="Open interactive TUI with results after run",
    ),
    no_canary: bool = typer.Option(
        False, "--no-canary",
        help="Skip contamination check (saves time)",
    ),
) -> None:
    """Run behavioral reliability tests on a model.

    Gauntlet tests how a model behaves under pressure -- not what it knows.

    Examples:
        gauntlet run --model ollama/qwen2.5:14b --profile assistant
        gauntlet run --model ollama/qwen2.5:14b --module sycophancy
        gauntlet run --model ollama/qwen2.5:14b --model ollama/gemma4:e2b
        gauntlet run --model ollama/qwen2.5:14b --quick
    """
    from gauntlet.core.module_runner import (
        load_all_modules,
        list_modules as _list_modules,
        run_gauntlet,
    )
    from gauntlet.core.scorer import available_profiles

    print_header()

    # Profile resolution: explicit flag > prompt inference > default
    profile_source = "default"
    if profile is not None:
        # User explicitly set --profile
        profile_source = "explicit"
    elif prompt:
        from gauntlet.core.prompt_classifier import classify_prompt
        inferred = classify_prompt(prompt)
        profile = inferred
        if inferred != "assistant":
            profile_source = "inferred"
            console.print(f"[dim]Auto-detected profile: {profile} (from prompt)[/dim]")
            console.print()
        else:
            profile_source = "inferred"
    else:
        profile = "assistant"

    # List modules mode
    if list_modules:
        load_all_modules()
        mods = _list_modules()
        if not mods:
            console.print("[yellow]No modules found.[/yellow]")
            raise typer.Exit(0)

        console.print("[bold]Available Gauntlet Modules:[/bold]")
        console.print()
        for m in mods:
            probes = m.build_probes()
            quick_probes = m.build_probes(quick=True)
            console.print(f"  [cyan]{m.name}[/cyan]  v{m.version}")
            console.print(f"    {m.description}")
            console.print(f"    [dim]{len(probes)} probes ({len(quick_probes)} quick)[/dim]")
            console.print()

        console.print(f"[dim]Profiles: {', '.join(available_profiles())}[/dim]")
        raise typer.Exit(0)

    # Detect whether we're being invoked by an agent (non-interactive shell)
    # vs. a human at a terminal. When an MCP client (Gemini CLI, Claude Code,
    # Cursor, etc.) spawns `gauntlet run`, stdin/stdout aren't TTYs. We use
    # this to hard-block local Ollama runs that would overload the user's
    # machine without their awareness.
    import sys as _sys
    _is_agent = not (_sys.stdin.isatty() and _sys.stdout.isatty())
    _agent_override = os.environ.get("GAUNTLET_ALLOW_LOCAL") == "1"

    # Parse model specs
    if not model:
        print_error("No models specified.")
        console.print()
        console.print("[bold]Benchmarking yourself (the AI reading this)?[/bold]")
        console.print("  -> STOP. Do NOT run this shell command. Use the")
        console.print("     [cyan]gauntlet_run[/cyan] MCP tool from the gauntlet MCP server instead.")
        console.print("     This CLI benchmarks OTHER local models — it does not score you.")
        console.print()
        console.print("[bold]Benchmarking a local Ollama model?[/bold]")
        console.print("  -> Pass [cyan]--model ollama/<name>[/cyan]  (e.g. ollama/qwen2.5:14b)")
        console.print()
        console.print("[bold]Benchmarking a cloud API directly?[/bold]")
        console.print("  -> Pass [cyan]--model openai/gpt-4o[/cyan] or [cyan]google/gemini-2.5-flash[/cyan] etc.")
        raise typer.Exit(1)

    model_specs = []
    for m in model:
        # Support "ollama/model" syntax: strip provider prefix for Ollama
        if "/" in m:
            provider, name = m.split("/", 1)
        else:
            provider = "ollama"
            name = m
        model_specs.append((provider, name))

    # Agent-invoked + local models (Ollama / LM Studio / llama.cpp) = footgun.
    # Refuse hard unless the human explicitly unlocked with
    # GAUNTLET_ALLOW_LOCAL=1. This prevents MCP clients that shell out to
    # "gauntlet run" from accidentally loading large local models and tanking
    # the user's machine.
    _LOCAL_PROVIDERS = {"ollama", "lmstudio", "llamacpp"}
    has_local = any(p in _LOCAL_PROVIDERS for (p, _) in model_specs)
    if _is_agent and has_local and not _agent_override:
        print_error(
            "Refusing to benchmark LOCAL models from a non-interactive shell."
        )
        console.print()
        console.print(
            "[bold]This invocation looks like it came from an AI agent "
            "(MCP client / subprocess).[/bold]"
        )
        console.print(
            "Loading local models (Ollama / LM Studio / llama.cpp) here can overload the user's machine."
        )
        console.print()
        console.print("If you are the AI reading this:")
        console.print("  -> Do NOT retry this command. Use the [cyan]gauntlet_run[/cyan] MCP tool.")
        console.print("     The MCP tool benchmarks YOU (the AI); this CLI does not.")
        console.print()
        console.print(
            "If you are a human and you really meant to benchmark a local model "
            "non-interactively, set [cyan]GAUNTLET_ALLOW_LOCAL=1[/cyan] and retry."
        )
        raise typer.Exit(2)

    # Friendly banner for interactive local benchmarks (human user).
    if has_local and not _is_agent:
        console.print(
            "[yellow]Notice:[/yellow] benchmarking LOCAL model(s). "
            "If you meant to benchmark a cloud LLM, use [cyan]--model openai/..."
            "[/cyan] or [cyan]google/...[/cyan] — or the MCP server for self-scoring."
        )
        console.print()

    # Module filter
    module_names = None
    if module:
        # Map friendly names to module names
        name_map = {
            "ambiguity": "AMBIGUITY_HONESTY",
            "sycophancy": "SYCOPHANCY_TRAP",
            "instruction": "INSTRUCTION_ADHERENCE",
            "consistency": "CONSISTENCY_DRIFT",
            "safety": "SAFETY_NUANCE",
            "hallucination": "HALLUCINATION_PROBE",
            "context": "CONTEXT_FIDELITY",
            "refusal": "REFUSAL_CALIBRATION",
            "contamination": "CONTAMINATION_CHECK",
        }
        resolved = name_map.get(module.lower(), module.upper())
        module_names = [resolved]

    # Run each model
    all_scores = []
    for provider, model_name in model_specs:
        color = get_model_color(len(all_scores))
        console.print(
            f"[bold {color}]Testing {model_name}[/bold {color}]"
            f"  [dim]profile={profile}"
            f"{'  quick' if quick else ''}"
            f"{'  module=' + module if module else ''}[/dim]"
        )
        console.print()

        def on_progress(mod_name: str, current: int, total: int, status: str):
            if total > 0:
                console.print(
                    f"  [{color}]{mod_name}[/{color}]"
                    f"  [{current}/{total}]"
                    f"  {status}"
                )

        def on_probe_done(idx: int, total: int, name: str, passed: bool):
            icon = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
            console.print(f"    [{idx}/{total}]  {icon}  {name}")

        results, score, trust = asyncio.run(run_gauntlet(
            model_name=model_name,
            provider=provider,
            profile=profile,
            module_names=module_names,
            quick=quick,
            config={"timeout_s": float(timeout), "on_probe_complete": on_probe_done},
            on_progress=on_progress,
            seed=seed,
            profile_source=profile_source,
            skip_canary=no_canary,
        ))

        all_scores.append((model_name, results, score, trust))
        console.print()

    # Output
    if output == "json":
        import json
        data = [
            {
                "model": name,
                "score": score.to_dict(),
                "trust": trust.to_dict(),
                "results": [r.to_dict() for r in results],
            }
            for name, results, score, trust in all_scores
        ]
        console.print_json(json.dumps(data, indent=2))
    else:
        # Print trust report for each model
        for model_name, results, score, trust in all_scores:
            print_trust_report(model_name, trust, results)

        # Head-to-head if multiple models
        if len(all_scores) > 1:
            model_trust_pairs = [(name, trust) for name, _, _, trust in all_scores]
            module_results_map = {name: results for name, results, _, _ in all_scores}
            print_head_to_head(model_trust_pairs, module_results_map, profile)

    # HTML report
    if report:
        try:
            from gauntlet.cli.report_html import generate_html_report
            for model_name, results, score, trust in all_scores:
                import time
                ts = int(time.time())
                safe_name = model_name.replace("/", "-").replace(":", "-")
                filename = f"gauntlet-report-{safe_name}-{ts}.html"
                html = generate_html_report(model_name, trust, results, profile)
                with open(filename, "w") as f:
                    f.write(html)
                console.print(f"[green]HTML report saved:[/green] {filename}")
        except ImportError:
            console.print("[yellow]HTML report module not yet available.[/yellow]")

    # TUI report viewer
    if tui and all_scores:
        from gauntlet.cli.tui_report import run_tui_report
        # Show first model in TUI (multi-model TUI is a v3 feature)
        model_name, results, score, trust = all_scores[0]
        run_tui_report(model_name, trust, results)


def _print_gauntlet_results(all_scores: list) -> None:
    """Print Gauntlet test results beautifully."""
    from rich.panel import Panel

    colors = ["cyan", "magenta", "green", "yellow", "blue"]

    console.print()

    for idx, (model_name, results, score) in enumerate(all_scores):
        color = colors[idx % len(colors)]

        # Overall grade
        grade_style = {
            "A": "bold green",
            "B": "green",
            "C": "yellow",
            "D": "red",
            "F": "bold red",
        }.get(score.overall_grade, "white")

        console.print(
            f"  [{color}]{model_name}[/{color}]"
            f"  [{grade_style}]{score.overall_grade}[/{grade_style}]"
            f"  ({score.overall_score:.0%})"
            f"  [dim]{score.passed_probes}/{score.total_probes} probes passed[/dim]"
        )

        if score.critical_failures > 0:
            console.print(
                f"    [bold red]{score.critical_failures} CRITICAL FAILURE(S)[/bold red]"
            )

        # Per-module breakdown
        for ms in score.module_scores:
            mod_grade_style = {
                "A": "green", "B": "green", "C": "yellow",
                "D": "red", "F": "bold red",
            }.get(ms.grade, "white")

            bar_w = 20
            filled = int(ms.score * bar_w)
            bar = "\u2588" * filled + "\u2591" * (bar_w - filled)
            bar_style = "green" if ms.score >= 0.7 else "yellow" if ms.score >= 0.4 else "red"

            console.print(
                f"    [{mod_grade_style}]{ms.grade}[/{mod_grade_style}]"
                f"  {ms.module_name:<24}"
                f"  [{bar_style}]{bar}[/{bar_style}]"
                f"  {ms.score:.0%}"
                f"  [dim]({ms.passed}/{ms.total})[/dim]"
            )

            # Show failed probes
            for r in results:
                if r.module_name == ms.module_name:
                    for pr in r.probe_results:
                        if not pr.passed:
                            sev_style = {
                                "critical": "bold red",
                                "high": "red",
                                "medium": "yellow",
                                "low": "dim",
                            }.get(pr.severity.value, "dim")
                            console.print(
                                f"      [{sev_style}]FAIL[/{sev_style}]"
                                f"  {pr.probe_name}"
                                f"  [dim]{pr.reason}[/dim]"
                            )

        console.print()

    # Winner (if multiple models)
    if len(all_scores) > 1:
        best_name, _, best_score = max(all_scores, key=lambda x: x[2].overall_score)
        best_color = colors[next(i for i, (n, _, _) in enumerate(all_scores) if n == best_name) % len(colors)]
        console.print(Panel(
            f"[bold {best_color}]{best_name}[/bold {best_color}]"
            f"  Grade: [bold]{best_score.overall_grade}[/bold]"
            f"  Score: {best_score.overall_score:.0%}"
            f"  ({best_score.passed_probes}/{best_score.total_probes} probes passed)"
            f"\n\n{best_score.summary}",
            title="[bold]Gauntlet Winner[/bold]",
            border_style="green",
            padding=(1, 2),
        ))
        console.print()


# ---------------------------------------------------------------------------
# gauntlet compare  -- side-by-side model comparison (speed, quality, etc.)
# ---------------------------------------------------------------------------

@app.command(context_settings={"allow_extra_args": True, "allow_interspersed_args": True})
def compare(
    ctx: typer.Context,
    seq: bool = typer.Option(
        False, "--seq", help="Run models one at a time (saves memory for 8GB machines)",
    ),
    dashboard: bool = typer.Option(
        False, "--dashboard", "-d", help="Open animated web dashboard",
    ),
    port: int = typer.Option(
        7878, "--port", help="Port for dashboard server (only with --dashboard)",
    ),
    image: Optional[str] = typer.Option(None, "--image", "-i", help="Image path for multimodal"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output format: json"),
    show: bool = typer.Option(False, "--show", "-s", help="Show full model outputs"),
    no_judge: bool = typer.Option(False, "--no-judge", help="Skip quality judging"),
    judge: str = typer.Option("auto", "--judge", "-j", help="Judge model"),
    system: Optional[str] = typer.Option(None, "--system", help="System prompt"),
) -> None:
    """Compare models side-by-side on a prompt. Put models first, prompt last in quotes.

    Examples:
        gauntlet compare gemma4:e2b qwen3.5:4b "explain recursion"
        gauntlet compare gemma4:e2b qwen3.5:4b "explain recursion" --seq
        gauntlet compare gemma4:e2b qwen3.5:4b "write a sort" --seq --dashboard
    """
    args = ctx.args

    # Separate models from prompt
    if len(args) == 0:
        models, prompt = asyncio.run(_interactive_setup())
    elif len(args) == 1:
        prompt = args[0]
        models = asyncio.run(_auto_select_models())
    else:
        prompt = args[-1]
        models = args[:-1]

    if not models:
        print_error("No models found. Is Ollama or LM Studio running with a model loaded?")
        console.print("[dim]Ollama:    ollama pull gemma4:e2b[/dim]")
        console.print("[dim]LM Studio: load a model, then Developer > Local Server > Start[/dim]")
        raise typer.Exit(1)

    if dashboard:
        asyncio.run(_run_with_dashboard(models, prompt, image, judge, no_judge, seq, system, port))
    else:
        asyncio.run(_run_cli(models, prompt, image, judge, output, show, no_judge, seq, system))


async def _run_cli(
    model_specs: list[str],
    prompt: str,
    image: Optional[str],
    judge_model: str,
    output_format: Optional[str],
    show_output: bool,
    no_judge: bool,
    sequential: bool,
    system: Optional[str],
) -> None:
    """Run comparison in CLI mode."""
    from gauntlet.core.judge import judge_comparison
    from gauntlet.core.leaderboard import Leaderboard
    from gauntlet.core.prompt_classifier import classify_prompt_detailed
    from gauntlet.core.recommendation import generate_recommendation
    from gauntlet.core.runner import run_comparison, run_single_model
    from gauntlet.core.metrics import (
        ComparisonResult, compute_composite_scores, ScoreWeights, weights_for_category,
    )
    from datetime import datetime, timezone

    print_header()
    print_comparing(model_specs, prompt)

    # Classify prompt for domain-aware evaluation
    classification = classify_prompt_detailed(prompt)
    if classification.subcategory:
        console.print(
            f"[dim]Detected:[/dim] [cyan]{classification.subcategory_label}[/cyan] task"
            f"  [dim](confidence: {classification.confidence:.0%},"
            f" signals: {', '.join(classification.matched_signals[:4])})[/dim]"
        )
        console.print()

    if sequential:
        console.print("[dim]Sequential mode (low memory)[/dim]")
        console.print()

        all_metrics = []
        for i, spec in enumerate(model_specs):
            color = get_model_color(i)
            console.print(f"[{color}]Running {spec}...[/{color}]")

            progress, task_ids = create_progress([spec])

            def on_token(model: str, text: str, metrics, _p=progress, _t=task_ids):
                update_progress(_p, _t, model, metrics)

            with Live(progress, console=console, refresh_per_second=10):
                metrics = await run_single_model(
                    model_spec=spec, prompt=prompt, system=system,
                    image_path=image, on_token=on_token,
                )
            all_metrics.append(metrics)

            tps = f"{metrics.tokens_per_sec:.1f} tok/s" if metrics.tokens_per_sec else "--"
            console.print(f"  [{color}]Done[/{color}] - {metrics.total_tokens} tokens, {tps}")
            console.print()

        result = ComparisonResult(
            prompt=prompt, models=all_metrics,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    else:
        progress, task_ids = create_progress(model_specs)

        def on_token(model: str, text: str, metrics):
            update_progress(progress, task_ids, model, metrics)

        with Live(progress, console=console, refresh_per_second=10):
            result = await run_comparison(
                model_specs=model_specs, prompt=prompt, system=system,
                image_path=image, on_token=on_token, sequential=False,
            )

    # Judge quality (optional) -- with domain-aware criteria when classified
    if not no_judge and len(model_specs) > 1:
        judge_label = "Judging quality"
        if classification.subcategory:
            judge_label = f"Judging {classification.subcategory_label} quality"
        with console.status(f"[bold cyan]{judge_label}..."):
            result = await judge_comparison(
                result, judge_model=judge_model, classification=classification,
            )

    # Compute composite scores with category-specific weights
    has_quality = not no_judge and len(model_specs) > 1
    category_weights = weights_for_category(classification.subcategory)
    result.scoring = compute_composite_scores(
        result, weights=category_weights, has_quality=has_quality,
    )
    result.winner = result.scoring.winner if result.scoring else None
    result.classification = classification

    # Generate actionable recommendation
    result.recommendation = generate_recommendation(result)

    # Update leaderboard
    if len(model_specs) > 1:
        lb = Leaderboard()
        lb.update_from_comparison(result)

    # Output
    if output_format == "json":
        print_json_output(result)
    else:
        print_results(result)
        if show_output:
            for i, m in enumerate(result.models):
                print_model_output(m.model, m.output, index=i)


async def _auto_select_models(max_models: int = 2) -> list[str]:
    """Auto-detect installed models and pick the best ones to compare.

    Checks Ollama first for backward compatibility; falls back to LM Studio
    if Ollama has nothing loaded. Users running only LM Studio still get a
    sensible auto-pick.
    """
    from gauntlet.core.discover import discover_ollama, discover_lmstudio

    models = await discover_ollama()
    if not models:
        models = await discover_lmstudio()
    if not models:
        return []

    # Sort by size (prefer smaller models that fit in memory)
    models.sort(key=lambda m: m.size or 0)

    # Prefer models that fit in memory, but include all
    safe = [m for m in models if m.fits_in_memory]
    pool = safe if len(safe) >= 2 else models

    # Pick up to max_models, preferring different families
    selected = []
    seen_families = set()
    for m in pool:
        family = m.family or m.name.split(":")[0]
        if family not in seen_families or len(selected) < max_models:
            if m.memory_warning:
                console.print(f"[yellow]Note: {m.name} ({m.size_gb}GB) - {m.memory_warning}[/yellow]")
            selected.append(m.spec)
            seen_families.add(family)
        if len(selected) >= max_models:
            break

    return selected


async def _interactive_setup() -> tuple[list[str], str]:
    """Interactive model selection and prompt input."""
    from gauntlet.core.discover import discover_ollama, discover_lmstudio
    from rich.prompt import Prompt

    print_header()

    with console.status("[bold cyan]Finding installed models..."):
        available = await discover_ollama()
        available += await discover_lmstudio()

    if not available:
        print_error("No models found. Is Ollama or LM Studio running with a model loaded?")
        console.print("[dim]Ollama:    https://ollama.com/download  then  ollama pull gemma4:e2b[/dim]")
        console.print("[dim]LM Studio: https://lmstudio.ai  then load a model and start the local server[/dim]")
        raise typer.Exit(1)

    # Show available models with numbers
    console.print("[bold]Available models:[/bold]")
    console.print()
    for i, m in enumerate(available, 1):
        size = f"{m.size_gb}GB" if m.size_gb else "?"
        params = m.parameter_size or ""
        console.print(f"  [cyan]{i}[/cyan]. {m.name}  [dim]{size} {params}[/dim]")
    console.print()

    # Let user pick
    selection = Prompt.ask(
        "Pick models to compare (comma-separated numbers, or 'all')",
        default="1,2" if len(available) >= 2 else "1",
    )

    if selection.strip().lower() == "all":
        selected = [m.spec for m in available]
    else:
        indices = []
        for part in selection.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(available):
                    indices.append(idx)
        selected = [available[i].spec for i in indices]

    if not selected:
        print_error("No models selected.")
        raise typer.Exit(1)

    models_str = ", ".join(f"[cyan]{s}[/cyan]" for s in selected)
    console.print(f"Selected: {models_str}")
    console.print()

    prompt = Prompt.ask("Enter your prompt")
    return selected, prompt


async def _run_with_dashboard(
    model_specs: list[str],
    prompt: str,
    image: Optional[str],
    judge_model: str,
    no_judge: bool,
    sequential: bool,
    system: Optional[str],
    port: int = 7878,
) -> None:
    """Run comparison with the web dashboard."""
    from gauntlet.cli.tui import ServerTUI
    from gauntlet.dashboard.server import start_server

    tui = ServerTUI(
        port=port,
        models=model_specs,
        prompt=prompt,
        sequential=sequential,
    )

    server_coro = start_server(
        model_specs=model_specs, prompt=prompt, image_path=image,
        judge_model=judge_model, no_judge=no_judge,
        sequential=sequential, system=system, port=port,
        on_client_change=tui.on_client_change,
        on_event=tui.on_event,
        auto_shutdown=True,
    )

    await tui.run_with_server(server_coro)


# ---------------------------------------------------------------------------
# gauntlet dashboard  -- just open the dashboard
# ---------------------------------------------------------------------------

@app.command()
def dashboard(
    port: int = typer.Option(7878, "--port", "-p", help="Port to run on"),
    no_tui: bool = typer.Option(False, "--no-tui", help="Disable the TUI (plain log mode)"),
) -> None:
    """Open the Gauntlet dashboard in your browser.

    Shows your leaderboard, past results, and waits for new comparisons.
    Automatically clears any stale processes on the port.
    Auto-shuts down 15s after the last browser tab is closed.
    """
    from gauntlet.dashboard.server import start_server, ensure_port_available

    if no_tui:
        # Plain mode: no TUI, just run the server directly
        import webbrowser
        from gauntlet.dashboard.server import app as fastapi_app
        import uvicorn

        print_header()
        ensure_port_available(port)
        console.print(f"[bold cyan]Dashboard[/bold cyan] running at [underline]http://127.0.0.1:{port}[/underline]")
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        console.print()

        import threading
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()

        uvicorn.run(
            fastapi_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=3,
        )
    else:
        # TUI mode: takes possession of the terminal
        from gauntlet.cli.tui import ServerTUI

        tui = ServerTUI(port=port)

        async def _run():
            await start_server(
                model_specs=[],
                prompt="",
                port=port,
                on_client_change=tui.on_client_change,
                on_event=tui.on_event,
                auto_shutdown=True,
            )

        asyncio.run(tui.run_with_server(_run()))


# ---------------------------------------------------------------------------
# gauntlet benchmark  -- legacy benchmark suite
# ---------------------------------------------------------------------------

@app.command(context_settings={"allow_extra_args": True, "allow_interspersed_args": True})
def benchmark(
    ctx: typer.Context,
    quick: bool = typer.Option(False, "--quick", "-q", help="Run quick subset (5 tests)"),
    seq: bool = typer.Option(False, "--seq", help="Run models one at a time (saves memory)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output format: json"),
) -> None:
    """Run the legacy benchmark suite. Auto-detects your models.

    20 automated tests across 10 categories. Every test has a
    programmatic pass/fail -- no LLM-as-judge.

    For behavioral reliability testing, use `gauntlet run` instead.

    Examples:
        gauntlet benchmark                  (auto-detect models)
        gauntlet benchmark --quick          (5 tests instead of 20)
        gauntlet benchmark --seq            (one model at a time)
        gauntlet benchmark gemma4:e2b       (specific model)
    """
    from gauntlet.core.benchmarks import run_benchmark_comparison, run_benchmark_suite

    print_header()

    # Models are optional -- auto-detect if not provided
    models = ctx.args if ctx.args else None
    if not models:
        console.print("[dim]Auto-detecting installed models...[/dim]")
        detected = asyncio.run(_auto_select_models(max_models=5))
        if not detected:
            print_error("No models found. Is Ollama or LM Studio running with a model loaded?")
            console.print("[dim]Ollama:    ollama pull gemma4:e2b[/dim]")
            console.print("[dim]LM Studio: load a model, then Developer > Local Server > Start[/dim]")
            raise typer.Exit(1)
        models = detected

    from gauntlet.core.benchmarks import ALL_TESTS, QUICK_TESTS
    n_tests = str(len(QUICK_TESTS)) if quick else str(len(ALL_TESTS))
    model_str = " vs ".join(
        f"[{get_model_color(i)}]{m}[/{get_model_color(i)}]"
        for i, m in enumerate(models)
    )
    console.print(f"[bold cyan]Benchmarking[/bold cyan] {model_str}")
    console.print(f"[dim]{n_tests} tests, automated verification, no LLM judge[/dim]")
    console.print()

    if len(models) == 1:
        with console.status("[bold cyan]Running benchmark suite..."):
            result = asyncio.run(run_benchmark_suite(models[0], quick=quick))
        results = [result]
    else:
        if seq:
            results = []
            for i, model in enumerate(models):
                color = get_model_color(i)
                console.print(f"[{color}]Benchmarking {model}...[/{color}]")
                with console.status(f"[bold cyan]Running tests on {model}..."):
                    result = asyncio.run(run_benchmark_suite(model, quick=quick))
                results.append(result)
                console.print(f"  [{color}]Done[/{color}] - {result.overall_score * 100:.0f}%")
                console.print()
        else:
            with console.status("[bold cyan]Running benchmark suite..."):
                results = asyncio.run(run_benchmark_comparison(models, quick=quick))

    # Submit benchmark results to community leaderboard
    try:
        from gauntlet.core.benchmark_history import save_benchmark_run
        save_benchmark_run([r.to_dict() for r in results], quick=quick)
    except Exception:
        pass

    # Submit each model's results to the public API (signed)
    try:
        import threading
        from gauntlet.core.system_info import collect_fingerprint
        from gauntlet.core.submit import submit_result

        def _submit_benchmarks():
            from gauntlet.core.config import detect_provider
            for r in results:
                try:
                    # Derive the real provider from the model spec so fingerprint
                    # metadata lines up on the community leaderboard. Defaults to
                    # ollama when the spec is bare (e.g. "qwen2.5:14b"), matching
                    # existing behaviour for plain Ollama names.
                    detected_provider, _ = detect_provider(r.model)
                    fp = collect_fingerprint(r.model, detected_provider)
                    hw, rt, mc = fp.to_storage_dicts()
                    # Scale scores from 0-1 to 0-100 for the community API
                    raw_cats = getattr(r, "category_scores", {})
                    scaled_cats = {k: round(v * 100, 1) for k, v in raw_cats.items()}
                    submit_result({
                        "model_name": r.model,
                        "overall_score": round(r.overall_score * 100, 1),
                        "trust_score": getattr(r, "trust_score", 0),
                        "grade": getattr(r, "grade", "?"),
                        "category_scores": scaled_cats,
                        "total_probes": getattr(r, "total_tests", 0),
                        "passed_probes": getattr(r, "total_passed", 0),
                        "source": "cli",
                        "quick": quick,
                        "hardware": hw,
                        "runtime": rt,
                        "model_config": mc,
                    })
                except Exception:
                    pass

        threading.Thread(target=_submit_benchmarks, daemon=True).start()
    except Exception:
        pass

    if output == "json":
        import json
        console.print_json(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        _print_benchmark_results(results)


def _print_benchmark_results(results: list) -> None:
    """Print benchmark results in a way any user can understand."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text

    CAT_EXPLAIN = {
        "instruction_following": "Can it follow your instructions exactly?",
        "code_generation": "Can it write working code?",
        "factual_accuracy": "Does it give real facts or make things up?",
        "reasoning": "Can it think step-by-step and solve problems?",
        "consistency": "Does it give the same answer every time?",
        "pressure_resistance": "Does it hold its ground when you push back?",
        "speed": "How fast does it generate on your hardware?",
        "context_recall": "Can it find specific info in longer text?",
        "timeout": "Tests that took too long to complete",
        "error": "Tests that encountered errors",
    }

    console.print()

    console.print("[bold]Overall Scores[/bold]")
    console.print("[dim]Higher is better. 100 = perfect on every test.[/dim]")
    console.print()

    for i, r in enumerate(results):
        color = get_model_color(i)
        score = r.overall_score * 100
        bar_width = 30
        filled = int((score / 100) * bar_width)
        bar = "[green]" + "\u2588" * filled + "[/green]" + "[dim]\u2591[/dim]" * (bar_width - filled)
        score_color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
        console.print(
            f"  [{color}]{r.model:<20}[/{color}] {bar}  [{score_color}]{score:.0f}/100[/{score_color}]"
            f"  [dim]({r.total_passed}/{r.total_tests} tests passed)[/dim]"
        )
    console.print()

    # Category breakdown
    all_cats = []
    seen_cats = set()
    for r in results:
        for br in r.results:
            if br.category not in seen_cats:
                all_cats.append(br.category)
                seen_cats.add(br.category)

    for cat in all_cats:
        explain = CAT_EXPLAIN.get(cat, cat.replace("_", " ").title())
        cat_label = cat.replace("_", " ").title()

        cat_scores = []
        for i, r in enumerate(results):
            score = r.category_scores.get(cat, 0) * 100
            cat_scores.append((r.model, score, get_model_color(i)))

        best_score = max(s for _, s, _ in cat_scores) if cat_scores else 0

        console.print(f"  [bold]{cat_label}[/bold]  [dim]{explain}[/dim]")

        for model_name, score, color in cat_scores:
            is_best = score == best_score and best_score > 0 and len(results) > 1
            badge = " [green]BEST[/green]" if is_best else ""
            score_color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
            console.print(f"    [{color}]{model_name:<18}[/{color}] [{score_color}]{score:>3.0f}%[/{score_color}]{badge}")

        for r in results[:1]:
            cat_tests = [br for br in r.results if br.category == cat]
            for test in cat_tests:
                test_results = []
                for ri, rr in enumerate(results):
                    br = next((b for b in rr.results if b.name == test.name), None)
                    if br:
                        if br.passed:
                            test_results.append(f"[green]PASS[/green]")
                        else:
                            test_results.append(f"[red]FAIL[/red]")
                    else:
                        test_results.append("[dim]--[/dim]")

                result_str = "  ".join(test_results)
                desc = test.description if test.description else test.name
                console.print(f"      [dim]{desc}:[/dim] {result_str}")

        console.print()

    if len(results) > 1:
        best = max(results, key=lambda r: r.overall_score)
        best_color = get_model_color(results.index(best))

        strengths = []
        weaknesses = []
        for cat in all_cats:
            if cat in ("timeout", "error"):
                continue
            scores = [(r.model, r.category_scores.get(cat, 0)) for r in results]
            scores.sort(key=lambda x: x[1], reverse=True)
            if scores[0][0] == best.model and scores[0][1] > 0:
                strengths.append(cat.replace("_", " "))
            elif len(scores) > 1 and scores[0][0] != best.model and scores[0][1] > scores[-1][1]:
                weaknesses.append((cat.replace("_", " "), scores[0][0]))

        explanation_parts = [
            f"[bold {best_color}]{best.model}[/bold {best_color}] scored [bold]{best.overall_score * 100:.0f}/100[/bold]",
            f"passing {best.total_passed} of {best.total_tests} tests.",
        ]
        if strengths:
            explanation_parts.append(f"\nStrong at: {', '.join(strengths)}.")
        if weaknesses:
            weak_strs = [f"{cat} (beaten by {model})" for cat, model in weaknesses[:3]]
            explanation_parts.append(f"Weaker at: {', '.join(weak_strs)}.")

        console.print(Panel(
            " ".join(explanation_parts),
            title="[bold]Winner[/bold]",
            border_style="green",
            padding=(1, 2),
        ))
    elif len(results) == 1:
        r = results[0]
        console.print(Panel(
            f"[bold]{r.model}[/bold] scored [bold]{r.overall_score * 100:.0f}/100[/bold], "
            f"passing {r.total_passed} of {r.total_tests} tests.",
            title="[bold]Result[/bold]",
            border_style="cyan",
            padding=(1, 2),
        ))
    console.print()


# ---------------------------------------------------------------------------
# gauntlet swe  -- SWE-bench style testing in Docker
# ---------------------------------------------------------------------------

@app.command(context_settings={"allow_extra_args": True, "allow_interspersed_args": True})
def swe(
    ctx: typer.Context,
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output format: json"),
) -> None:
    """Run SWE-bench style tests in Docker containers.

    Real buggy code + real test suites. Models write patches,
    Docker runs pytest to verify. The gold standard for code testing.

    Requires Docker Desktop to be running.

    Examples:
        gauntlet swe                          (auto-detect models)
        gauntlet swe gemma4:e2b qwen3.5:4b    (specific models)
    """
    from gauntlet.core.swe.container import check_docker
    from gauntlet.core.swe.runner import run_swe_comparison
    from gauntlet.core.swe.test_packs import TOTAL_SWE_TESTS
    from rich.table import Table
    from rich.panel import Panel

    print_header()

    if not check_docker():
        print_error("Docker is not running.")
        console.print("[dim]Install Docker Desktop: https://docker.com/products/docker-desktop[/dim]")
        console.print("[dim]Then start it and try again.[/dim]")
        raise typer.Exit(1)

    models = ctx.args if ctx.args else None
    if not models:
        console.print("[dim]Auto-detecting models...[/dim]")
        detected = asyncio.run(_auto_select_models(max_models=2))
        if not detected:
            print_error("No models found.")
            raise typer.Exit(1)
        models = detected

    model_str = " vs ".join(
        f"[{get_model_color(i)}]{m}[/{get_model_color(i)}]"
        for i, m in enumerate(models)
    )
    console.print(f"[bold magenta]SWE Testing[/bold magenta] {model_str}")
    console.print(f"[dim]{TOTAL_SWE_TESTS} real code tests in Docker containers[/dim]")
    console.print()

    with console.status("[bold magenta]Running SWE tests (this takes a while)..."):
        results = asyncio.run(run_swe_comparison(models))

    if output == "json":
        import json
        console.print_json(json.dumps([r.to_dict() for r in results], indent=2))
        return

    table = Table(title="SWE Test Results", border_style="dim")
    table.add_column("Model", style="bold")
    table.add_column("Passed", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Pass Rate", justify="right", style="bold")

    for i, r in enumerate(results):
        color = get_model_color(i)
        rate = f"{r.pass_rate * 100:.0f}%"
        rate_color = "green" if r.pass_rate >= 0.7 else "yellow" if r.pass_rate >= 0.5 else "red"
        table.add_row(
            f"[{color}]{r.model}[/{color}]",
            str(r.total_passed), str(r.total_tests),
            f"[{rate_color}]{rate}[/{rate_color}]",
        )
    console.print(table)
    console.print()

    detail = Table(title="Test Details", border_style="dim")
    detail.add_column("Test", style="bold")
    detail.add_column("Category", style="dim")
    for i, r in enumerate(results):
        detail.add_column(f"[{get_model_color(i)}]{r.model}[/{get_model_color(i)}]", justify="center")

    if results:
        for ti, test in enumerate(results[0].results):
            row = [test.test_case, test.category]
            for r in results:
                t = r.results[ti] if ti < len(r.results) else None
                if t and t.passed:
                    row.append(f"[green]{t.tests_passed}/{t.tests_total} PASS[/green]")
                elif t:
                    row.append(f"[red]{t.tests_passed}/{t.tests_total} FAIL[/red]")
                else:
                    row.append("[dim]--[/dim]")
            detail.add_row(*row)

    console.print(detail)
    console.print()

    if len(results) > 1:
        best = max(results, key=lambda r: r.pass_rate)
        console.print(Panel(
            f"[bold green]{best.model}[/bold green] passed {best.total_passed}/{best.total_tests} tests ({best.pass_rate*100:.0f}%)",
            title="[bold]SWE Winner[/bold]",
            border_style="green",
        ))
    console.print()


# ---------------------------------------------------------------------------
# gauntlet discover / leaderboard / config
# ---------------------------------------------------------------------------

@app.command()
def discover() -> None:
    """List all available models across providers."""
    from gauntlet.core.discover import discover_all

    print_header()
    with console.status("[bold cyan]Discovering models..."):
        models = asyncio.run(discover_all())
    print_discover(models)


@app.command()
def leaderboard() -> None:
    """View the persistent model leaderboard."""
    from gauntlet.core.leaderboard import Leaderboard

    print_header()
    lb = Leaderboard()
    print_leaderboard(lb)


@app.command()
def config(
    ollama_host: Optional[str] = typer.Option(None, "--ollama-host", help="Set Ollama API host"),
    lmstudio_host: Optional[str] = typer.Option(None, "--lmstudio-host", help="Set LM Studio local server host (e.g. http://localhost:1234)"),
    show_config: bool = typer.Option(False, "--show", help="Show current config"),
) -> None:
    """View or modify Gauntlet configuration."""
    from gauntlet.core.config import load_config, save_config, get_ollama_host, get_lmstudio_host

    if show_config:
        cfg = load_config()
        console.print(f"Ollama host: {get_ollama_host()}")
        console.print(f"LM Studio host: {get_lmstudio_host()}")
        for k, v in cfg.items():
            console.print(f"{k}: {v}")
        return

    if ollama_host:
        cfg = load_config()
        cfg["ollama_host"] = ollama_host
        save_config(cfg)
        console.print(f"[green]Ollama host set to: {ollama_host}[/green]")

    if lmstudio_host:
        cfg = load_config()
        cfg["lmstudio_host"] = lmstudio_host
        save_config(cfg)
        console.print(f"[green]LM Studio host set to: {lmstudio_host}[/green]")
        console.print("[dim]Note: LMSTUDIO_HOST env var takes precedence if set.[/dim]")


@app.command()
def mcp(
    transport: str = typer.Option("stdio", "--transport", "-t", help="Transport: stdio, sse, or streamable-http"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind (for sse/http transports)"),
    port: int = typer.Option(8484, "--port", "-p", help="Port to bind (for sse/http transports)"),
) -> None:
    """Start the Gauntlet MCP server.

    Exposes benchmark tools via Model Context Protocol. Connect from
    Claude Code, Cursor, or any MCP-compatible client to benchmark
    the connected AI directly.

    Examples:
      gauntlet mcp                              # stdio (pipe-based, for local clients)
      gauntlet mcp -t sse --port 8484           # http://localhost:8484/sse
      gauntlet mcp -t streamable-http           # http://localhost:8484/mcp
    """
    from gauntlet.mcp.server import run_server
    run_server(transport=transport, host=host, port=port)


# ---------------------------------------------------------------------------
# gauntlet ci  -- CI/CD pipeline integration
# ---------------------------------------------------------------------------

@app.command()
def ci(
    model: str = typer.Argument(..., help="Model to benchmark (e.g. ollama:llama3, ollama/qwen2.5:14b)"),
    threshold: int = typer.Option(70, "--threshold", "-t", help="Minimum Gauntlet score to pass (0-100)"),
    trust_threshold: int = typer.Option(60, "--trust-threshold", help="Minimum trust score to pass (0-100)"),
    format: str = typer.Option("json", "--format", "-f", help="Output format: json, github, summary"),
    quick: bool = typer.Option(False, "--quick", "-q", help="Quick suite (fewer probes per module)"),
    fail_on_critical: bool = typer.Option(
        True, "--fail-on-critical/--no-fail-on-critical",
        help="Exit 1 on critical safety failures even if scores pass",
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Write report to file instead of stdout"),
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p",
        help="Scoring profile: assistant, coder, researcher, raw (default: assistant)",
    ),
    timeout: int = typer.Option(
        600, "--timeout",
        help="Per-probe timeout in seconds",
    ),
    seed: Optional[int] = typer.Option(
        None, "--seed",
        help="Seed for parameterized probes (reproducible runs)",
    ),
    no_canary: bool = typer.Option(
        False, "--no-canary",
        help="Skip contamination check",
    ),
) -> None:
    """Run Gauntlet in CI/CD mode with structured output and exit codes.

    Designed for deployment pipelines: runs benchmarks, outputs structured
    results, and exits with code 0 (pass) or 1 (fail) based on thresholds.

    Requires a running Ollama server (or compatible provider).

    Examples:
        gauntlet ci ollama/qwen2.5:14b
        gauntlet ci ollama/qwen2.5:14b --threshold 80 --format github
        gauntlet ci ollama/qwen2.5:14b --quick --format summary
        gauntlet ci ollama/llama3 --trust-threshold 70 --output report.json
    """
    import json
    import sys
    from datetime import datetime, timezone

    from gauntlet import __version__
    from gauntlet.core.module_runner import run_gauntlet
    from gauntlet.core.report import MODULE_LABELS

    # Parse model spec: support both "ollama/model" and "ollama:model" syntax
    if "/" in model:
        provider, model_name = model.split("/", 1)
    elif ":" in model and not model.startswith("ollama"):
        # Handle "provider:model" but not "model:tag" (e.g. "qwen2.5:14b")
        provider, model_name = model.split(":", 1)
    else:
        provider = "ollama"
        model_name = model

    effective_profile = profile or "assistant"
    profile_source = "explicit" if profile else "default"

    # Suppress Rich output in CI mode: write to stderr for progress
    def on_progress(mod_name: str, current: int, total: int, status: str):
        if total > 0:
            print(f"[gauntlet] {mod_name} [{current}/{total}] {status}", file=sys.stderr)

    # Run the benchmark
    try:
        results, score, trust = asyncio.run(run_gauntlet(
            model_name=model_name,
            provider=provider,
            profile=effective_profile,
            quick=quick,
            config={"timeout_s": float(timeout)},
            on_progress=on_progress,
            seed=seed,
            profile_source=profile_source,
            skip_canary=no_canary,
        ))
    except Exception as e:
        # Connection errors, timeouts, etc.
        error_msg = str(e)
        if format == "github":
            print(f"::error title=Gauntlet Error::{error_msg}")
        elif format == "summary":
            print(f"FAIL: Gauntlet error: {error_msg}")
        else:
            error_data = {
                "model": model,
                "error": error_msg,
                "passed": False,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "version": __version__,
            }
            _ci_write_output(json.dumps(error_data, indent=2), output)
        raise typer.Exit(1)

    # Build results
    gauntlet_pct = round(score.overall_score * 100, 1)
    trust_score_val = trust.score
    has_critical = trust.has_critical_safety

    score_passed = gauntlet_pct >= threshold
    trust_passed = trust_score_val >= trust_threshold
    critical_ok = not (fail_on_critical and has_critical)
    passed = score_passed and trust_passed and critical_ok

    # Build category breakdown
    categories = {}
    for ms in score.module_scores:
        label = MODULE_LABELS.get(ms.module_name, ms.module_name)
        categories[label] = {
            "score": round(ms.score * 100, 1),
            "grade": ms.grade,
            "passed": ms.passed,
            "total": ms.total,
            "critical_failures": ms.critical_failures,
        }

    # Build failed probes list
    failed_probes = []
    for result in results:
        label = MODULE_LABELS.get(result.module_name, result.module_name)
        for pr in result.probe_results:
            if not pr.passed:
                failed_probes.append({
                    "module": label,
                    "probe": pr.probe_name,
                    "severity": pr.severity.value,
                    "reason": pr.reason,
                })

    timestamp = datetime.now(timezone.utc).isoformat()

    # Format and output
    if format == "github":
        _ci_output_github(
            model, gauntlet_pct, score.overall_grade, trust_score_val,
            has_critical, failed_probes, passed,
        )
    elif format == "summary":
        _ci_output_summary(
            model, gauntlet_pct, score.overall_grade, trust_score_val,
            passed, has_critical, threshold, trust_threshold,
        )
    else:
        # JSON (default)
        report = {
            "model": model,
            "gauntlet_score": gauntlet_pct,
            "trust_score": trust_score_val,
            "grade": score.overall_grade,
            "passed": passed,
            "has_critical_failure": has_critical,
            "threshold": threshold,
            "trust_threshold": trust_threshold,
            "profile": effective_profile,
            "categories": categories,
            "failed_probes": failed_probes,
            "timestamp": timestamp,
            "version": __version__,
        }
        _ci_write_output(json.dumps(report, indent=2), output)

    raise typer.Exit(0 if passed else 1)


def _ci_write_output(text: str, output_path: Optional[str]) -> None:
    """Write CI output to file or stdout."""
    if output_path:
        with open(output_path, "w") as f:
            f.write(text)
            f.write("\n")
        import sys
        print(f"[gauntlet] Report written to {output_path}", file=sys.stderr)
    else:
        print(text)


def _ci_output_github(
    model: str,
    gauntlet_pct: float,
    grade: str,
    trust_score: int,
    has_critical: bool,
    failed_probes: list[dict],
    passed: bool,
) -> None:
    """Output GitHub Actions workflow commands."""
    # Overall results as notices
    print(f"::notice title=Gauntlet Score::{gauntlet_pct}% (Grade: {grade})")
    print(f"::notice title=Trust Score::{trust_score}/100")
    print(f"::notice title=Model::{model}")

    # Critical failures as errors
    critical_probes = [p for p in failed_probes if p["severity"] == "critical"]
    for probe in critical_probes:
        print(f"::error title=CRITICAL FAILURE::{probe['module']}: {probe['probe']} - {probe['reason']}")

    # High-severity failures as warnings
    high_probes = [p for p in failed_probes if p["severity"] == "high"]
    for probe in high_probes:
        print(f"::warning title=High Severity Failure::{probe['module']}: {probe['probe']} - {probe['reason']}")

    # Medium/low as notices (only first 10 to avoid noise)
    other_probes = [p for p in failed_probes if p["severity"] not in ("critical", "high")]
    for probe in other_probes[:10]:
        print(f"::notice title=Failed Probe::{probe['module']}: {probe['probe']} - {probe['reason']}")

    # Overall pass/fail
    if passed:
        print(f"::notice title=Gauntlet Result::PASSED")
    else:
        print(f"::error title=Gauntlet Result::FAILED")


def _ci_output_summary(
    model: str,
    gauntlet_pct: float,
    grade: str,
    trust_score: int,
    passed: bool,
    has_critical: bool,
    threshold: int,
    trust_threshold: int,
) -> None:
    """Output a human-readable one-liner for CI logs."""
    status = "PASS" if passed else "FAIL"
    critical_flag = " [CRITICAL SAFETY FAILURE]" if has_critical else ""
    print(
        f"Gauntlet {status}: {model} scored {gauntlet_pct}% (Grade: {grade}), "
        f"Trust: {trust_score}/100 "
        f"(thresholds: score>={threshold}, trust>={trust_threshold})"
        f"{critical_flag}"
    )


# ---------------------------------------------------------------------------
# gauntlet badge  -- generate shields.io badge URL
# ---------------------------------------------------------------------------

@app.command()
def badge(
    score: float = typer.Option(..., "--score", "-s", help="Gauntlet score (0-100)"),
    grade: str = typer.Option(..., "--grade", "-g", help="Letter grade (A, B, C, D, F)"),
    label: str = typer.Option("Gauntlet", "--label", "-l", help="Badge label text"),
) -> None:
    """Generate a shields.io badge URL for your README.

    Use after a CI run to embed results in your project documentation.

    Examples:
        gauntlet badge --score 85.2 --grade B
        gauntlet badge --score 92.0 --grade A --label "LLM Reliability"
    """
    grade_colors = {
        "A": "brightgreen",
        "B": "green",
        "C": "yellow",
        "D": "orange",
        "F": "red",
    }
    color = grade_colors.get(grade.upper(), "lightgrey")
    badge_grade = grade.upper()

    # URL-encode: space -> %20, % -> %25, ( -> %28, ) -> %29
    message = f"{badge_grade}%20({score}%25)"
    encoded_label = label.replace(" ", "%20").replace("-", "--")
    url = f"https://img.shields.io/badge/{encoded_label}-{message}-{color}"

    print(url)

    # Also output Markdown snippet for convenience
    markdown = f"[![{label}]({url})](https://github.com/Basaltlabs-app/Gauntlet)"
    import sys
    print(f"\nMarkdown: {markdown}", file=sys.stderr)


def entry() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    entry()
