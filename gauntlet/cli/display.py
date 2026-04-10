"""Rich terminal display for Gauntlet CLI output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from gauntlet.core.discover import DiscoveredModel
from gauntlet.core.leaderboard import Leaderboard
from gauntlet.core.metrics import ComparisonResult, ModelMetrics


console = Console()

# Color palette for models
MODEL_COLORS = [
    "cyan",
    "magenta",
    "green",
    "yellow",
    "blue",
    "red",
    "bright_cyan",
    "bright_magenta",
]


def get_model_color(index: int) -> str:
    return MODEL_COLORS[index % len(MODEL_COLORS)]


def print_header() -> None:
    """Print the Gauntlet header with optional update notice."""
    header = Text()
    header.append("  GAUNTLET  ", style="bold white on blue")
    header.append("  Behavioral reliability under pressure.", style="dim")
    console.print()
    console.print(header)

    # Non-blocking update check (uses cached result or triggers background fetch)
    try:
        from gauntlet.core.update_check import get_update_message
        msg = get_update_message()
        if msg:
            console.print(f"  [yellow]{msg}[/yellow]")
    except Exception:
        pass

    console.print()


def print_comparing(model_specs: list[str], prompt: str) -> None:
    """Print what we're about to compare."""
    console.print(f"[dim]Prompt:[/dim] {prompt[:120]}{'...' if len(prompt) > 120 else ''}")
    models_text = " vs ".join(
        f"[{get_model_color(i)}]{spec}[/{get_model_color(i)}]"
        for i, spec in enumerate(model_specs)
    )
    console.print(f"[dim]Models:[/dim] {models_text}")
    console.print()


def create_progress(model_specs: list[str]) -> tuple[Progress, dict[str, int]]:
    """Create a progress display for streaming generation."""
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=30),
        TextColumn("{task.fields[tokens]} tokens"),
        TextColumn("{task.fields[tps]} tok/s"),
        TimeElapsedColumn(),
        console=console,
    )
    task_ids = {}
    for i, spec in enumerate(model_specs):
        color = get_model_color(i)
        task_id = progress.add_task(
            f"[{color}]{spec}",
            total=None,
            tokens=0,
            tps="--",
        )
        task_ids[spec] = task_id
    return progress, task_ids


def update_progress(
    progress: Progress,
    task_ids: dict[str, int],
    model: str,
    metrics: ModelMetrics,
) -> None:
    """Update progress display with latest metrics."""
    # Match by model name in task_ids (may need to check original spec too)
    task_id = None
    for spec, tid in task_ids.items():
        if model in spec or spec in model:
            task_id = tid
            break

    if task_id is None:
        return

    tps = f"{metrics.tokens_per_sec:.1f}" if metrics.tokens_per_sec else "--"
    progress.update(
        task_id,
        advance=1,
        tokens=metrics._token_count,
        tps=tps,
    )


def print_results(result: ComparisonResult) -> None:
    """Print the full comparison results."""
    console.print()

    # Summary table
    table = Table(
        title="Results",
        show_header=True,
        header_style="bold",
        border_style="dim",
    )
    table.add_column("Model", style="bold")
    table.add_column("Tokens/sec", justify="right")
    table.add_column("TTFT", justify="right")
    table.add_column("Total Time", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Memory", justify="right")
    table.add_column("Quality", justify="right")
    table.add_column("", justify="center")

    for i, m in enumerate(result.models):
        color = get_model_color(i)
        is_winner = m.model == result.winner

        tps = f"{m.tokens_per_sec:.1f}" if m.tokens_per_sec else "--"
        ttft = f"{m.ttft_ms:.0f}ms" if m.ttft_ms else "--"
        total = f"{m.total_time_s:.1f}s" if m.total_time_s else "--"
        tokens = str(m.total_tokens) if m.total_tokens else "--"
        memory = (
            f"{m.peak_memory_delta_mb:+.1f}MB"
            if m.peak_memory_delta_mb is not None
            else "--"
        )
        quality = f"{m.overall_score:.1f}/10" if m.overall_score else "--"
        badge = "[bold green]WINNER[/bold green]" if is_winner else ""

        style = f"bold {color}" if is_winner else color
        table.add_row(
            f"[{style}]{m.model}[/{style}]",
            tps,
            ttft,
            total,
            tokens,
            memory,
            quality,
            badge,
        )

    console.print(table)

    # Quality breakdown if available -- dynamic columns for domain-specific criteria
    scored_models = [m for m in result.models if m.quality_scores]
    if scored_models:
        console.print()
        qtable = Table(
            title="Quality Breakdown",
            show_header=True,
            header_style="bold",
            border_style="dim",
        )
        qtable.add_column("Model", style="bold")

        # Discover column names from the first scored model's quality_scores keys
        dim_names = list(scored_models[0].quality_scores.keys())
        for dim_name in dim_names:
            qtable.add_column(dim_name, justify="center")

        for i, m in enumerate(scored_models):
            color = get_model_color(i)
            s = m.quality_scores
            row = [f"[{color}]{m.model}[/{color}]"]
            for dim_name in dim_names:
                row.append(_score_cell(s.get(dim_name, 0)))
            qtable.add_row(*row)

        console.print(qtable)

        # Show specific issues if any model has them
        models_with_issues = [
            m for m in result.models
            if hasattr(m, "specific_issues") and m.specific_issues
        ]
        if models_with_issues:
            console.print()
            for m in models_with_issues:
                color = get_model_color(
                    next(
                        (i for i, rm in enumerate(result.models) if rm.model == m.model),
                        0,
                    )
                )
                issues_text = "; ".join(m.specific_issues[:5])
                console.print(
                    f"  [{color}]{m.model}[/{color}]"
                    f"  [yellow]Issues:[/yellow] {issues_text}"
                )

    # Scoring breakdown (the real explanation)
    if result.scoring:
        print_scoring_breakdown(result.scoring)

    # Recommendation (the actionable advice)
    if result.recommendation:
        console.print(
            Panel(
                result.recommendation,
                title="[bold]Recommendation[/bold]",
                border_style="cyan",
                padding=(1, 2),
            )
        )

    if result.judge_model:
        console.print(f"[dim]Judged by: {result.judge_model}[/dim]")
    console.print()


def _score_cell(score: int | float) -> str:
    """Format a score with color coding."""
    score = float(score)
    if score >= 8:
        return f"[green]{score:.0f}[/green]"
    elif score >= 6:
        return f"[yellow]{score:.0f}[/yellow]"
    else:
        return f"[red]{score:.0f}[/red]"


def print_scoring_breakdown(scoring) -> None:
    """Print the composite scoring breakdown -- shows exactly WHY the winner won."""
    console.print()

    # Formula
    console.print(f"[dim]Scoring: {scoring.formula}[/dim]")
    console.print()

    # Scoring table
    table = Table(
        title="Composite Scoring",
        show_header=True,
        header_style="bold",
        border_style="dim",
    )
    table.add_column("Model", style="bold")
    table.add_column("Composite", justify="right", style="bold")

    # Get component names from first model
    if scoring.model_scores:
        for comp in scoring.model_scores[0].components:
            table.add_column(comp.metric_name, justify="right")

    for i, ms in enumerate(scoring.model_scores):
        color = get_model_color(i)
        is_winner = ms.model == scoring.winner

        row = [
            f"[{'bold ' + color if is_winner else color}]{ms.model}[/]",
            f"[{'bold green' if is_winner else 'white'}]{ms.composite:.2f}[/]",
        ]
        for comp in ms.components:
            rank_badge = " [green]#1[/green]" if comp.rank == 1 and len(scoring.model_scores) > 1 else ""
            row.append(f"{comp.raw_value:.1f} {comp.raw_unit}{rank_badge}")
        table.add_row(*row)

    console.print(table)

    # Winner explanation
    if scoring.winner and scoring.winner_reason:
        console.print()
        console.print(
            Panel(
                f"[bold green]{scoring.winner}[/bold green]\n\n{scoring.winner_reason}",
                title="[bold]Winner[/bold]",
                border_style="green",
                padding=(1, 2),
            )
        )
    console.print()


def print_model_output(model: str, output: str, index: int = 0) -> None:
    """Print a model's full output in a panel."""
    color = get_model_color(index)
    console.print(
        Panel(
            output,
            title=f"[bold {color}]{model}[/bold {color}]",
            border_style=color,
            padding=(1, 2),
        )
    )


def print_discover(models: list[DiscoveredModel]) -> None:
    """Print discovered models."""
    if not models:
        console.print("[yellow]No models found. Is Ollama running?[/yellow]")
        return

    # Group by provider
    by_provider: dict[str, list[DiscoveredModel]] = {}
    for m in models:
        by_provider.setdefault(m.provider, []).append(m)

    for provider, provider_models in by_provider.items():
        table = Table(
            title=f"{provider.upper()} Models",
            show_header=True,
            header_style="bold",
            border_style="dim",
        )
        table.add_column("Model", style="bold cyan")
        table.add_column("Size", justify="right")
        table.add_column("Parameters", justify="right")
        table.add_column("Quantization")
        table.add_column("Family")
        table.add_column("Vision", justify="center")
        table.add_column("Spec", style="dim")

        for m in provider_models:
            size = f"{m.size_gb}GB" if m.size_gb else "--"
            params = m.parameter_size or "--"
            quant = m.quantization or "--"
            family = m.family or "--"
            vision = "[green]Yes[/green]" if m.multimodal else "[dim]--[/dim]"
            table.add_row(m.name, size, params, quant, family, vision, m.spec)

        console.print(table)
        console.print()

    console.print(f"[dim]Total: {len(models)} models across {len(by_provider)} providers[/dim]")


def print_leaderboard(leaderboard: Leaderboard) -> None:
    """Print the persistent leaderboard."""
    ratings = leaderboard.sorted_ratings()

    if not ratings:
        console.print("[yellow]No leaderboard data yet. Run some comparisons first![/yellow]")
        return

    table = Table(
        title="Gauntlet Leaderboard",
        show_header=True,
        header_style="bold",
        border_style="dim",
    )
    table.add_column("#", style="dim", justify="right")
    table.add_column("Model", style="bold")
    table.add_column("Rating", justify="right", style="bold")
    table.add_column("W/L/D", justify="center")
    table.add_column("Win Rate", justify="right")
    table.add_column("Avg tok/s", justify="right")
    table.add_column("Avg Quality", justify="right")
    table.add_column("Comparisons", justify="right")

    for i, r in enumerate(ratings):
        rank = str(i + 1)
        if i == 0:
            rank = "[gold1]1[/gold1]"
        elif i == 1:
            rank = "[grey70]2[/grey70]"
        elif i == 2:
            rank = "[dark_orange3]3[/dark_orange3]"

        rating_str = f"{r.rating:.0f}"
        if r.rating >= 1600:
            rating_str = f"[green]{rating_str}[/green]"
        elif r.rating < 1400:
            rating_str = f"[red]{rating_str}[/red]"

        wld = f"{r.wins}/{r.losses}/{r.draws}"
        win_rate = f"{r.win_rate * 100:.0f}%"
        avg_tps = f"{r.avg_tokens_sec:.1f}" if r.avg_tokens_sec else "--"
        avg_q = f"{r.avg_quality:.1f}/10" if r.avg_quality else "--"

        color = get_model_color(i)
        table.add_row(
            rank,
            f"[{color}]{r.name}[/{color}]",
            rating_str,
            wld,
            win_rate,
            avg_tps,
            avg_q,
            str(r.total_comparisons),
        )

    console.print(table)
    console.print()


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[bold red]Error:[/bold red] {message}")


def print_json_output(result: ComparisonResult) -> None:
    """Print results as JSON for scripting."""
    import json
    console.print_json(json.dumps(result.to_dict(), indent=2))


def print_trust_report(
    model_name: str,
    trust: "TrustScore",
    module_results: list | None = None,
) -> None:
    """Print the Gauntlet trust report to terminal."""
    from rich.panel import Panel
    from rich.table import Table

    console.print()

    # Header
    profile_label = trust.profile
    if trust.profile_source == "inferred":
        profile_label += " (auto-detected from prompt)"
    elif trust.profile_source == "explicit":
        profile_label += " (explicit)"

    # Trust score with color
    if trust.score >= 90:
        score_style = "bold green"
    elif trust.score >= 75:
        score_style = "green"
    elif trust.score >= 60:
        score_style = "yellow"
    elif trust.score >= 40:
        score_style = "red"
    else:
        score_style = "bold red"

    header_lines = [
        f"[bold]GAUNTLET REPORT[/bold] -- [cyan]{model_name}[/cyan]",
        f"Profile: {profile_label}",
        f"Trust Score: [{score_style}]{trust.score}/100[/{score_style}]",
    ]
    if trust.seed is not None:
        header_lines.append(f"[dim]Seed: {trust.seed}[/dim]")

    console.print(Panel(
        "\n".join(header_lines),
        border_style="cyan",
        padding=(1, 2),
    ))

    # Critical safety warning
    if trust.has_critical_safety:
        console.print(Panel(
            "[bold red]CRITICAL SAFETY FAILURE[/bold red]\n"
            "This model complied with harmful requests. Not safe for production.",
            border_style="red",
        ))

    # Contamination warning
    if trust.contamination_warning:
        console.print(Panel(
            "[bold yellow]CONTAMINATION WARNING[/bold yellow]\n"
            "This model may have been trained on Gauntlet test data. Results may be inflated.",
            border_style="yellow",
        ))

    # Per-module probe breakdown
    if module_results:
        from gauntlet.core.modules.base import Severity
        from gauntlet.core.report import MODULE_LABELS

        console.print()
        console.print("[bold]MODULE BREAKDOWN:[/bold]")

        for mr in module_results:
            if mr.module_name == "CONTAMINATION_CHECK":
                continue

            label = MODULE_LABELS.get(mr.module_name, mr.module_name)
            rate = mr.pass_rate

            if rate >= 0.9:
                bar_color = "green"
            elif rate >= 0.6:
                bar_color = "yellow"
            else:
                bar_color = "red"

            console.print(
                f"\n  [{bar_color}]■[/{bar_color}] [bold]{label}[/bold]"
                f"  [{bar_color}]{rate:.0%}[/{bar_color}]"
                f"  [dim]({mr.passed_probes}/{mr.total_probes} passed)[/dim]"
            )

            # Show individual probes in a compact table
            probe_table = Table(
                show_header=True,
                header_style="dim bold",
                border_style="dim",
                box=None,
                padding=(0, 1),
                pad_edge=False,
            )
            probe_table.add_column("", width=6)  # pass/fail
            probe_table.add_column("Probe", min_width=30)
            probe_table.add_column("Severity", width=10)
            probe_table.add_column("Reason", ratio=1)

            for pr in mr.probe_results:
                if pr.passed:
                    status = "[green]PASS[/green]"
                else:
                    status = "[red]FAIL[/red]"

                sev_styles = {
                    Severity.CRITICAL: "[bold red]CRIT[/bold red]",
                    Severity.HIGH: "[red]HIGH[/red]",
                    Severity.MEDIUM: "[yellow]MED[/yellow]",
                    Severity.LOW: "[dim]LOW[/dim]",
                }
                sev = sev_styles.get(pr.severity, str(pr.severity.value))

                reason = pr.reason[:80]
                if len(pr.reason) > 80:
                    reason += "…"

                probe_table.add_row(
                    f"  {status}",
                    pr.probe_name,
                    sev,
                    f"[dim]{reason}[/dim]",
                )

            console.print(probe_table)

    # Findings
    console.print()
    console.print("[bold]FINDINGS:[/bold]")

    for finding in trust.findings:
        if finding.level == "CRITICAL":
            icon = "[bold red]CRITICAL[/bold red]"
        elif finding.level == "WARNING":
            icon = "[yellow]WARNING [/yellow]"
        else:
            icon = "[green]CLEAN   [/green]"

        console.print(f"  {icon}  {finding.summary}")
        if finding.probe_id:
            console.print(
                f"           [dim]Probe: {finding.probe_id} | "
                f"Module: {finding.module_name} | "
                f"Deduction: -{finding.deduction:.1f}[/dim]"
            )

    console.print()


def print_head_to_head(
    model_scores: list[tuple[str, "TrustScore"]],
    module_results_map: dict[str, list] | None = None,
    profile: str = "raw",
) -> None:
    """Print head-to-head comparison table."""
    from rich.table import Table
    from rich.panel import Panel
    from gauntlet.core.report import generate_verdict, MODULE_LABELS

    if len(model_scores) < 2:
        return

    console.print()

    profile_labels = {
        "assistant": "assistant", "coder": "coder",
        "researcher": "researcher", "raw": "raw",
    }

    console.print(
        f"[bold]HEAD TO HEAD[/bold] -- {profile_labels.get(profile, profile)} profile"
    )
    console.print()

    # Score comparison
    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("", style="dim")
    for name, _ in model_scores:
        table.add_column(name, justify="center")

    # Trust score row
    table.add_row(
        "Trust Score",
        *[f"[bold]{ts.score}/100[/bold]" for _, ts in model_scores],
    )

    # Module pass rates (if we have module results)
    if module_results_map:
        all_modules = set()
        for results in module_results_map.values():
            for r in results:
                if r.module_name != "CONTAMINATION_CHECK":
                    all_modules.add(r.module_name)

        for mod_name in sorted(all_modules):
            label = MODULE_LABELS.get(mod_name, mod_name)
            cells = []
            for model_name, _ in model_scores:
                results = module_results_map.get(model_name, [])
                mod_result = next((r for r in results if r.module_name == mod_name), None)
                if mod_result:
                    rate = mod_result.pass_rate
                    filled = int(rate * 10)
                    bar = "[green]" + "#" * filled + "[/green]" + "[dim]" + "-" * (10 - filled) + "[/dim]"
                    cells.append(f"[{bar}] {mod_result.passed_probes}/{mod_result.total_probes}")
                else:
                    cells.append("[dim]--[/dim]")
            table.add_row(label, *cells)

    console.print(table)

    # Verdict
    verdict = generate_verdict(model_scores, profile=profile)
    if verdict:
        console.print()
        console.print(Panel(
            f"[bold]VERDICT:[/bold]\n  {verdict}",
            border_style="cyan",
        ))

    console.print()
