"""TUI Report Screen -- interactive trust report in the terminal.

Built on Textual. Shows bar charts for trust dimensions,
drill-down into probes, and side-by-side comparison.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Label
from textual.screen import Screen

from gauntlet.core.trust_score import TrustScore
from gauntlet.core.report import MODULE_LABELS
from gauntlet.core.modules.base import ModuleResult


class TrustBar(Static):
    """A single horizontal bar for a module pass rate."""

    def __init__(self, label: str, value: float, max_width: int = 40) -> None:
        filled = int(value * max_width)
        empty = max_width - filled

        if value >= 0.9:
            color = "green"
        elif value >= 0.6:
            color = "yellow"
        else:
            color = "red"

        bar = f"[{color}]{'█' * filled}[/{color}][dim]{'░' * empty}[/dim]"
        text = f"  {label:<20s} {bar} {value:.0%}"
        super().__init__(text)


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
    """Main trust report screen."""

    BINDINGS = [("q", "quit", "Quit"), ("escape", "quit", "Quit")]

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

            # Bar charts
            yield Static("\n[bold]TRUST DIMENSIONS[/bold]")
            for mr in self.module_results:
                if mr.module_name == "CONTAMINATION_CHECK":
                    continue
                label = MODULE_LABELS.get(mr.module_name, mr.module_name)
                yield TrustBar(label, mr.pass_rate)

            # Findings
            yield Static("\n[bold]FINDINGS[/bold]")
            for finding in self.trust.findings:
                yield FindingLine(finding)

        yield Footer()

    def action_quit(self) -> None:
        self.app.exit()


class TrustReportApp(App):
    """Textual app for viewing trust reports."""

    CSS = """
    ScrollableContainer {
        padding: 1 2;
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
