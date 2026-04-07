"""Gauntlet CLI - Typer-based command line interface."""

from __future__ import annotations

import asyncio
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
        help="Model to test (e.g. ollama/qwen2.5:14b). Can specify multiple.",
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

    # Parse model specs
    if not model:
        print_error("No models specified. Use --model ollama/qwen2.5:14b")
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

    # Module filter
    module_names = None
    if module:
        # Map friendly names to module names
        name_map = {
            "ambiguity": "AMBIGUITY_HONESTY",
            "sycophancy": "SYCOPHANCY_TRAP",
            "instruction": "INSTRUCTION_ADHERENCE",
            "consistency": "CONSISTENCY_DRIFT",
            "safety": "SAFETY_BOUNDARY",
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
        print_error("No models found. Is Ollama running? Do you have models installed?")
        console.print("[dim]Run: ollama pull gemma4:e2b[/dim]")
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
    from gauntlet.core.runner import run_comparison, run_single_model
    from gauntlet.core.metrics import ComparisonResult, compute_composite_scores, ScoreWeights
    from datetime import datetime, timezone

    print_header()
    print_comparing(model_specs, prompt)

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

    # Judge quality (optional)
    if not no_judge and len(model_specs) > 1:
        with console.status("[bold cyan]Judging quality..."):
            result = await judge_comparison(result, judge_model=judge_model)

    # Compute composite scores and determine winner
    has_quality = not no_judge and len(model_specs) > 1
    result.scoring = compute_composite_scores(result, has_quality=has_quality)
    result.winner = result.scoring.winner if result.scoring else None

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
    """Auto-detect installed models and pick the best ones to compare."""
    from gauntlet.core.discover import discover_ollama

    models = await discover_ollama()
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
    from gauntlet.core.discover import discover_ollama
    from rich.prompt import Prompt

    print_header()

    with console.status("[bold cyan]Finding installed models..."):
        available = await discover_ollama()

    if not available:
        print_error("No models found. Is Ollama running?")
        console.print("[dim]Install: https://ollama.com/download[/dim]")
        console.print("[dim]Then: ollama pull gemma4:e2b[/dim]")
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
            print_error("No models found. Is Ollama running?")
            console.print("[dim]Run: ollama pull gemma4:e2b[/dim]")
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
    show_config: bool = typer.Option(False, "--show", help="Show current config"),
) -> None:
    """View or modify Gauntlet configuration."""
    from gauntlet.core.config import load_config, save_config, get_ollama_host

    if show_config:
        cfg = load_config()
        console.print(f"Ollama host: {get_ollama_host()}")
        for k, v in cfg.items():
            console.print(f"{k}: {v}")
        return

    if ollama_host:
        cfg = load_config()
        cfg["ollama_host"] = ollama_host
        save_config(cfg)
        console.print(f"[green]Ollama host set to: {ollama_host}[/green]")


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


def entry() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    entry()
