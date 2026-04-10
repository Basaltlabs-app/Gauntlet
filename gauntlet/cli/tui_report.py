"""TUI Report Screen -- interactive trust report in the terminal.

Built on Textual. Shows bar charts for trust dimensions,
click-to-expand probe drill-down, and side-by-side comparison.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static
from textual.screen import Screen

from gauntlet.core.trust_score import TrustScore
from gauntlet.core.report import MODULE_LABELS
from gauntlet.core.modules.base import ModuleResult, Severity

# ---------------------------------------------------------------------------
# Display constants
# ---------------------------------------------------------------------------

_MAX_NAME_LEN = 36              # probe name truncation threshold
_MAX_REASON_LEN = 60            # reason text truncation threshold
_DETAIL_SEPARATOR_WIDTH = 90    # width of the horizontal rule in detail rows

# ---------------------------------------------------------------------------
# Severity icons and colors
# ---------------------------------------------------------------------------

_SEVERITY_STYLE = {
    Severity.CRITICAL: ("⬤", "bold red"),
    Severity.HIGH: ("⬤", "red"),
    Severity.MEDIUM: ("◉", "yellow"),
    Severity.LOW: ("○", "dim"),
}


class ProbeRow(Static):
    """A single probe result row inside the expanded module detail."""

    def __init__(self, probe_result) -> None:
        pr = probe_result
        icon, sev_style = _SEVERITY_STYLE.get(
            pr.severity, ("○", "dim"),
        )

        if pr.passed:
            status = "[green]PASS[/green]"
        else:
            status = f"[{sev_style}]FAIL[/{sev_style}]"

        # Truncate probe name for display
        raw_name = pr.probe_name or ""
        name = raw_name[:_MAX_NAME_LEN]
        if len(raw_name) > _MAX_NAME_LEN:
            name += "…"

        # Truncate reason
        raw_reason = pr.reason or ""
        reason = raw_reason[:_MAX_REASON_LEN]
        if len(raw_reason) > _MAX_REASON_LEN:
            reason += "…"

        text = (
            f"    [{sev_style}]{icon}[/{sev_style}] "
            f"{status}  "
            f"{name:<38s} "
            f"[dim]{reason}[/dim]"
        )
        super().__init__(text)


class ModuleBar(Static):
    """A clickable horizontal bar that toggles probe drill-down."""

    def __init__(
        self,
        label: str,
        value: float,
        module_result: ModuleResult,
        max_width: int = 40,
    ) -> None:
        self._module_result = module_result
        self._expanded = False

        filled = int(value * max_width)
        empty = max_width - filled

        if value >= 0.9:
            color = "green"
        elif value >= 0.6:
            color = "yellow"
        else:
            color = "red"

        passed = module_result.passed_probes
        total = module_result.total_probes

        bar = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * empty}[/dim]"
        text = (
            f"  {label:<20s} {bar} {value:.0%} "
            f"[dim]({passed}/{total})[/dim] "
            f"[dim italic]▸ click to expand[/dim italic]"
        )
        super().__init__(text)

    async def on_click(self) -> None:
        """Toggle probe detail rows below this bar."""
        self._expanded = not self._expanded

        # Find the detail container that follows this bar
        detail_id = f"detail_{self._module_result.module_name}"
        try:
            detail = self.screen.query_one(f"#{detail_id}", Container)
            detail.display = self._expanded
        except Exception:
            # ID not found or not mounted yet — revert toggle
            self._expanded = not self._expanded


class ModuleDetail(Container):
    """Container for probe-level rows. Hidden by default, toggled by ModuleBar click."""

    def __init__(self, module_result: ModuleResult) -> None:
        super().__init__(id=f"detail_{module_result.module_name}")
        self._module_result = module_result

    def compose(self) -> ComposeResult:
        # Header row
        yield Static(
            f"    [bold dim]{'─' * _DETAIL_SEPARATOR_WIDTH}[/bold dim]\n"
            f"    [bold]Probe[/bold]{' ' * 36}"
            f"[bold]Result[/bold]  [bold]Details[/bold]"
        )

        for pr in self._module_result.probe_results:
            yield ProbeRow(pr)

        # Summary line
        failed = [
            p for p in self._module_result.probe_results if not p.passed
        ]
        if failed:
            crit = sum(1 for p in failed if p.severity == Severity.CRITICAL)
            high = sum(1 for p in failed if p.severity == Severity.HIGH)
            parts = []
            if crit:
                parts.append(f"[bold red]{crit} CRITICAL[/bold red]")
            if high:
                parts.append(f"[red]{high} HIGH[/red]")
            summary = ", ".join(parts) if parts else f"{len(failed)} failed"
            yield Static(f"    [dim]└─ {summary} failure(s)[/dim]")
        else:
            yield Static(f"    [dim]└─ All probes passed[/dim]")

        yield Static(f"    [bold dim]{'─' * _DETAIL_SEPARATOR_WIDTH}[/bold dim]")


class FindingLine(Static):
    """A single finding line."""

    def __init__(self, finding) -> None:
        if finding.level == "CRITICAL":
            icon = "[bold red]CRITICAL[/bold red]"
        elif finding.level == "WARNING":
            icon = "[yellow]WARNING [/yellow]"
        else:
            icon = "[green]CLEAN   [/green]"
        text = f"  {icon}  {finding.summary}"
        if finding.probe_id:
            text += f"\n           [dim]{finding.probe_id} | {finding.module_name} | -{finding.deduction:.1f}[/dim]"
        super().__init__(text)


class TrustReportScreen(Screen):
    """Main trust report screen with expandable module drill-down."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("a", "expand_all", "Expand All"),
        ("c", "collapse_all", "Collapse All"),
    ]

    def __init__(
        self,
        model_name: str,
        trust: TrustScore,
        module_results: list[ModuleResult],
    ) -> None:
        super().__init__()
        self.model_name = model_name
        self.trust = trust
        self.module_results = module_results

    def compose(self) -> ComposeResult:
        yield Header()

        with ScrollableContainer():
            # Title
            if self.trust.score >= 75:
                score_style = "green"
            elif self.trust.score >= 60:
                score_style = "yellow"
            else:
                score_style = "red"

            yield Static(
                f"[bold cyan]GAUNTLET REPORT[/bold cyan] -- [bold]{self.model_name}[/bold]\n"
                f"Profile: {self.trust.profile} ({self.trust.profile_source})\n"
                f"Trust Score: [bold {score_style}]{self.trust.score}/100[/bold {score_style}]"
                + (f"\n[dim]Seed: {self.trust.seed}[/dim]" if self.trust.seed else ""),
            )

            # Warnings
            if self.trust.has_critical_safety:
                yield Static("[bold red on dark_red] CRITICAL SAFETY FAILURE [/bold red on dark_red]")
            if self.trust.contamination_warning:
                yield Static("[bold yellow on dark_goldenrod] CONTAMINATION WARNING [/bold yellow on dark_goldenrod]")

            # Bar charts with expandable probe details
            yield Static("\n[bold]TRUST DIMENSIONS[/bold]  [dim]click bar to expand · a=expand all · c=collapse all[/dim]")
            for mr in self.module_results:
                if mr.module_name == "CONTAMINATION_CHECK":
                    continue
                label = MODULE_LABELS.get(mr.module_name, mr.module_name)
                yield ModuleBar(label, mr.pass_rate, mr)
                detail = ModuleDetail(mr)
                detail.display = False  # Start collapsed
                yield detail

            # Findings
            yield Static("\n[bold]FINDINGS[/bold]")
            for finding in self.trust.findings:
                yield FindingLine(finding)

        yield Footer()

    def action_quit(self) -> None:
        self.app.exit()

    def action_expand_all(self) -> None:
        """Expand all module detail panels."""
        for detail in self.query(ModuleDetail):
            detail.display = True
        for bar in self.query(ModuleBar):
            bar._expanded = True

    def action_collapse_all(self) -> None:
        """Collapse all module detail panels."""
        for detail in self.query(ModuleDetail):
            detail.display = False
        for bar in self.query(ModuleBar):
            bar._expanded = False


class TrustReportApp(App):
    """Textual app for viewing trust reports."""

    CSS = """
    ScrollableContainer {
        padding: 1 2;
    }
    ModuleDetail {
        padding: 0 0 0 2;
    }
    ModuleBar {
        height: auto;
    }
    ModuleBar:hover {
        background: $surface-lighten-1;
    }
    """

    def __init__(
        self,
        model_name: str,
        trust: TrustScore,
        module_results: list[ModuleResult],
    ) -> None:
        super().__init__()
        self.model_name = model_name
        self.trust = trust
        self.module_results = module_results

    def on_mount(self) -> None:
        self.push_screen(TrustReportScreen(
            self.model_name, self.trust, self.module_results,
        ))


def run_tui_report(
    model_name: str,
    trust: TrustScore,
    module_results: list[ModuleResult],
) -> None:
    """Launch the TUI report viewer."""
    app = TrustReportApp(model_name, trust, module_results)
    app.run()
