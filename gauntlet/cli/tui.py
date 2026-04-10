"""Gauntlet TUI - Full-screen interactive terminal interface.

A professional, clean Textual app for behavioral reliability testing.
Launches when you type `gauntlet`.
"""

from __future__ import annotations

import math
import random
from collections import deque
from datetime import datetime
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Static

import psutil
from rich.text import Text
from rich.panel import Panel
from rich.table import Table


# ---------------------------------------------------------------------------
# Obsidian Color Palette
# ---------------------------------------------------------------------------

_BRONZE = "#b08d6e"
_STEEL = "#7d93ab"
_SAGE = "#6ea882"
_GOLD = "#c4a05a"
_MAUVE = "#a87c94"
_TERRA = "#c27065"
_TEAL = "#5da4a8"
_KHAKI = "#9b8e78"
_BG = "#0c0d12"
_CARD = "#14151a"
_BORDER = "#1e2028"
_TEXT = "#d4d0c8"
_MUTED = "#6b6860"


# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------

LOGO_LINES = [
    r"   ____    _   _   _ _   _ _____ _     _____ _____  ",
    r"  / ___|  / \ | | | | \ | |_   _| |   | ____|_   _| ",
    r" | |  _  / _ \| | | |  \| | | | | |   |  _|   | |   ",
    r" | |_| |/ ___ \ |_| | |\  | | | | |___| |___  | |   ",
    r"  \____/_/   \_\___/|_| \_| |_| |_____|_____| |_|   ",
]


class AnimatedLogo(Static):
    """Brand logo with subtle breathing sweep in warm tones."""

    _tick = reactive(0)

    def on_mount(self) -> None:
        self.set_interval(0.12, self._step)

    def _step(self) -> None:
        self._tick += 1

    def watch__tick(self) -> None:
        self.refresh()

    def render(self) -> Text:
        t = self._tick
        result = Text()
        phase = (t % 80) / 80.0 * 2 * math.pi

        for line in LOGO_LINES:
            for col_idx, ch in enumerate(line):
                if ch == " ":
                    result.append(ch)
                    continue
                wave = math.sin(phase - col_idx * 0.12) * 0.5 + 0.5
                if wave > 0.75:
                    style = f"bold {_BRONZE}"
                elif wave > 0.4:
                    style = _KHAKI
                else:
                    style = _MUTED
                result.append(ch, style=style)
            result.append("\n")

        return result


class ScanBar(Static):
    """Subtle animated scan bar."""

    _tick = reactive(0)
    WIDTH = 52

    def on_mount(self) -> None:
        self.set_interval(0.08, self._step)

    def _step(self) -> None:
        self._tick += 1

    def watch__tick(self) -> None:
        self.refresh()

    def render(self) -> Text:
        pos = self._tick % (self.WIDTH * 2)
        if pos >= self.WIDTH:
            pos = self.WIDTH * 2 - pos

        result = Text()
        for i in range(self.WIDTH):
            dist = abs(i - pos)
            if dist == 0:
                result.append("\u2588", style=f"bold {_BRONZE}")
            elif dist == 1:
                result.append("\u2593", style=_KHAKI)
            elif dist == 2:
                result.append("\u2592", style=f"dim {_KHAKI}")
            elif dist == 3:
                result.append("\u2591", style=f"dim {_MUTED}")
            else:
                result.append("\u2500", style="#1a1a22")
        return result


# ---------------------------------------------------------------------------
# System Info Widget
# ---------------------------------------------------------------------------


class SystemInfo(Static):
    """System status: Ollama, RAM, models."""

    ollama_status = reactive("checking")
    model_count = reactive(0)
    _models: list[dict] = []

    def set_models(self, models: list[dict]) -> None:
        self._models = models
        self.model_count = len(models)
        self.ollama_status = "connected"
        self.refresh()

    def set_error(self) -> None:
        self._models = []
        self.ollama_status = "offline"
        self.refresh()

    def render(self) -> Text:
        result = Text()

        # Ollama status
        if self.ollama_status == "connected":
            result.append("  \u25cf", style=f"bold {_SAGE}")
            result.append(" Ollama", style=_SAGE)
        elif self.ollama_status == "checking":
            result.append("  \u25cb", style=_GOLD)
            result.append(" Checking", style=_GOLD)
        else:
            result.append("  \u25cf", style=f"bold {_TERRA}")
            result.append(" Offline", style=_TERRA)

        if self.model_count > 0:
            result.append(f"  {self.model_count} models", style=_MUTED)

        # RAM
        try:
            mem = psutil.virtual_memory()
            used_gb = mem.used / (1024**3)
            total_gb = mem.total / (1024**3)
            pct = mem.percent
            ram_clr = _SAGE if pct < 70 else _GOLD if pct < 90 else _TERRA
            result.append("  \u2502  ", style="#2a2a30")
            result.append(f"RAM {used_gb:.1f}/{total_gb:.1f}GB", style=f"dim {ram_clr}")
        except Exception:
            pass

        result.append("  \u2502  ", style="#2a2a30")
        from gauntlet import __version__
        result.append(f"v{__version__}", style=f"dim {_BRONZE}")

        result.append("\n\n")

        # Model list
        if self._models:
            result.append("  INSTALLED MODELS\n", style=f"bold {_MUTED}")
            for m in self._models[:8]:
                name = m.get("name", "?")
                size = m.get("size_gb")
                params = m.get("parameter_size", "")
                result.append("  \u2022 ", style=_BRONZE)
                result.append(name, style=f"bold {_TEXT}")
                if size:
                    result.append(f"  {size}GB", style=_MUTED)
                if params:
                    result.append(f"  {params}", style=_MUTED)
                result.append("\n")
            if len(self._models) > 8:
                result.append(f"  +{len(self._models) - 8} more\n", style=_MUTED)
        elif self.ollama_status == "offline":
            result.append("  No models found\n", style=f"dim {_GOLD}")
            result.append("  Is Ollama running?\n", style=_MUTED)
        elif self.ollama_status == "checking":
            result.append("  Scanning...\n", style=f"dim italic {_MUTED}")

        return result


# ---------------------------------------------------------------------------
# Screens: Discover, Leaderboard
# ---------------------------------------------------------------------------


class DiscoverScreen(Screen):
    """Full-screen view of all discovered models."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
    ]

    DEFAULT_CSS = f"""
    DiscoverScreen {{
        background: {_BG};
    }}
    #disc-header {{
        text-align: center;
        height: 3;
        padding: 1 0;
        color: {_BRONZE};
        text-style: bold;
    }}
    #disc-table {{
        height: 1fr;
        margin: 1 2;
    }}
    #disc-footer {{
        dock: bottom;
        height: 1;
        background: {_CARD};
        padding: 0 2;
        color: {_MUTED};
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static("DISCOVER MODELS", id="disc-header")
        yield DataTable(id="disc-table")
        yield Static("  Scanning for models...", id="disc-footer")

    def on_mount(self) -> None:
        table = self.query_one("#disc-table", DataTable)
        table.add_columns("Model", "Size", "Params", "Quant", "Family", "Vision")
        table.cursor_type = "row"
        table.zebra_stripes = True
        self._fetch()

    @work(thread=True)
    def _fetch(self) -> None:
        import asyncio
        from gauntlet.core.discover import discover_all

        try:
            models = asyncio.run(discover_all())
            self.app.call_from_thread(self._populate, models)
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))

    def _populate(self, models) -> None:
        table = self.query_one("#disc-table", DataTable)
        footer = self.query_one("#disc-footer", Static)

        if not models:
            footer.update("  No models found. Is Ollama running?  |  ESC back")
            return

        for m in models:
            table.add_row(
                m.name,
                f"{m.size_gb}GB" if m.size_gb else "?",
                m.parameter_size or "",
                m.quantization or "",
                m.family or "",
                "Yes" if m.multimodal else "",
            )

        providers = len(set(m.provider for m in models))
        footer.update(
            f"  {len(models)} models across {providers} provider(s)  |  ESC back"
        )

    def _show_error(self, msg: str) -> None:
        footer = self.query_one("#disc-footer", Static)
        footer.update(f"  Error: {msg}  |  ESC back")

    def action_go_back(self) -> None:
        self.dismiss()


class LeaderboardScreen(Screen):
    """Full-screen view of the persistent ELO leaderboard."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
    ]

    DEFAULT_CSS = f"""
    LeaderboardScreen {{
        background: {_BG};
    }}
    #lb-header {{
        text-align: center;
        height: 3;
        padding: 1 0;
        color: {_BRONZE};
        text-style: bold;
    }}
    #lb-table {{
        height: 1fr;
        margin: 1 2;
    }}
    #lb-footer {{
        dock: bottom;
        height: 1;
        background: {_CARD};
        padding: 0 2;
        color: {_MUTED};
    }}
    """

    def compose(self) -> ComposeResult:
        yield Static("LEADERBOARD", id="lb-header")
        yield DataTable(id="lb-table")
        yield Static("  Loading...", id="lb-footer")

    def on_mount(self) -> None:
        table = self.query_one("#lb-table", DataTable)
        table.add_columns(
            "#", "Model", "ELO", "W/L/D", "Win%", "tok/s", "Quality", "Runs"
        )
        table.cursor_type = "row"
        table.zebra_stripes = True
        self._fetch()

    @work(thread=True)
    def _fetch(self) -> None:
        from gauntlet.core.leaderboard import Leaderboard

        try:
            lb = Leaderboard()
            ratings = lb.sorted_ratings()
            self.app.call_from_thread(self._populate, ratings)
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))

    def _populate(self, ratings) -> None:
        table = self.query_one("#lb-table", DataTable)
        footer = self.query_one("#lb-footer", Static)

        if not ratings:
            footer.update(
                "  No leaderboard data yet. Run some comparisons first!  |  ESC back"
            )
            return

        for i, r in enumerate(ratings, 1):
            wld = f"{r.wins}/{r.losses}/{r.draws}"
            total = r.wins + r.losses + r.draws
            win_pct = f"{r.win_rate * 100:.0f}%" if total > 0 else "--"
            tps = f"{r.avg_tokens_sec:.1f}" if r.avg_tokens_sec else "--"
            qual = f"{r.avg_quality:.1f}" if r.avg_quality else "--"

            table.add_row(
                str(i),
                r.name,
                f"{r.elo:.0f}",
                wld,
                win_pct,
                tps,
                qual,
                str(r.total_comparisons),
            )

        footer.update(f"  {len(ratings)} models ranked  |  ESC back")

    def _show_error(self, msg: str) -> None:
        footer = self.query_one("#lb-footer", Static)
        footer.update(f"  Error: {msg}  |  ESC back")

    def action_go_back(self) -> None:
        self.dismiss()


# ---------------------------------------------------------------------------
# RunScreen - Model comparison
# ---------------------------------------------------------------------------


class RunScreen(Screen):
    """Pick models, enter prompt, compare live, see results."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]

    DEFAULT_CSS = f"""
    RunScreen {{
        background: {_BG};
    }}
    #run-header {{
        text-align: center;
        height: 3;
        padding: 1 0;
        color: {_BRONZE};
        text-style: bold;
    }}
    #run-body {{
        height: 1fr;
        margin: 0 2;
        overflow-y: auto;
    }}
    #run-model-list {{
        height: auto;
        margin: 0 0 1 0;
    }}
    #run-form {{
        height: auto;
        margin: 1 0;
    }}
    .run-label {{
        height: 1;
        margin: 1 0 0 0;
        color: {_MUTED};
    }}
    #run-models-input, #run-prompt-input {{
        margin: 0 0 1 0;
    }}
    #run-options {{
        height: auto;
        margin: 1 0;
    }}
    .opt-btn {{
        width: auto;
        min-width: 16;
        margin: 0 1 0 0;
        height: 3;
        background: {_CARD};
        color: {_MUTED};
        border: tall {_BORDER};
    }}
    .opt-btn.toggled {{
        background: #1a1510;
        color: {_BRONZE};
        border: tall {_BRONZE};
    }}
    #run-go {{
        width: auto;
        min-width: 20;
        height: 3;
        margin: 1 0;
        background: #1a1510;
        color: {_BRONZE};
        border: tall {_KHAKI};
    }}
    #run-go:hover, #run-go:focus {{
        background: #2a2018;
        border: tall {_BRONZE};
    }}
    #run-progress {{
        height: auto;
        margin: 1 0;
    }}
    #run-results {{
        height: auto;
        margin: 1 0;
    }}
    #run-done-buttons {{
        height: auto;
        margin: 1 0;
    }}
    #run-again {{
        width: auto;
        min-width: 16;
        height: 3;
        margin: 0 1 0 0;
        background: #1a1510;
        color: {_BRONZE};
        border: tall {_KHAKI};
    }}
    #run-back-btn {{
        width: auto;
        min-width: 16;
        height: 3;
        background: {_CARD};
        color: {_MUTED};
        border: tall {_BORDER};
    }}
    #run-footer {{
        dock: bottom;
        height: 1;
        background: {_CARD};
        padding: 0 2;
        color: {_MUTED};
    }}
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._available = []
        self._seq = False
        self._no_judge = False
        self._progress_data: dict[str, dict] = {}
        self._comparison_result = None

    def compose(self) -> ComposeResult:
        yield Static("MODEL COMPARISON", id="run-header")
        yield Container(
            Static("Scanning for models...", id="run-model-list"),
            Container(
                Static("Models (comma-sep numbers, or 'all'):", classes="run-label"),
                Input(placeholder="e.g. 1,2", id="run-models-input"),
                Static("Prompt:", classes="run-label"),
                Input(placeholder="Enter your prompt...", id="run-prompt-input"),
                Horizontal(
                    Button("Sequential", id="run-seq-btn", classes="opt-btn"),
                    Button("No Judge", id="run-nojudge-btn", classes="opt-btn"),
                    id="run-options",
                ),
                Button("Run", id="run-go"),
                id="run-form",
            ),
            Static("", id="run-progress"),
            Static("", id="run-results"),
            Horizontal(
                Button("Run Again", id="run-again"),
                Button("Back to Menu", id="run-back-btn"),
                id="run-done-buttons",
            ),
            id="run-body",
        )
        yield Static("  Loading models...  |  ESC back", id="run-footer")

    def on_mount(self) -> None:
        self.query_one("#run-form").display = False
        self.query_one("#run-progress").display = False
        self.query_one("#run-results").display = False
        self.query_one("#run-done-buttons").display = False
        self._fetch_models()

    @work(thread=True)
    def _fetch_models(self) -> None:
        import asyncio
        from gauntlet.core.discover import discover_ollama

        try:
            models = asyncio.run(discover_ollama())
            self.app.call_from_thread(self._show_models, models)
        except Exception as e:
            self.app.call_from_thread(self._show_model_error, str(e))

    def _show_models(self, models) -> None:
        self._available = models
        ml = self.query_one("#run-model-list", Static)

        if not models:
            ml.update(Text("  No models found. Is Ollama running?", style=_GOLD))
            self.query_one("#run-footer", Static).update("  No models  |  ESC back")
            return

        t = Text()
        t.append("  Available Models:\n", style=f"bold {_TEXT}")
        for i, m in enumerate(models, 1):
            size = f"{m.size_gb}GB" if m.size_gb else "?"
            params = m.parameter_size or ""
            t.append(f"   {i}. ", style=_BRONZE)
            t.append(f"{m.name}", style=f"bold {_TEXT}")
            t.append(f"  {size} {params}\n", style=_MUTED)

        ml.update(t)
        default = "1,2" if len(models) >= 2 else "1"
        self.query_one("#run-models-input", Input).value = default
        self.query_one("#run-form").display = True
        self.query_one("#run-footer", Static).update(
            "  Pick models, enter prompt, press Run  |  ESC back"
        )

    def _show_model_error(self, msg: str) -> None:
        self.query_one("#run-model-list", Static).update(
            Text(f"  Error: {msg}", style=_TERRA)
        )
        self.query_one("#run-footer", Static).update("  ESC back")

    @on(Button.Pressed, "#run-seq-btn")
    def _toggle_seq(self) -> None:
        self._seq = not self._seq
        btn = self.query_one("#run-seq-btn", Button)
        if self._seq:
            btn.add_class("toggled")
        else:
            btn.remove_class("toggled")

    @on(Button.Pressed, "#run-nojudge-btn")
    def _toggle_nojudge(self) -> None:
        self._no_judge = not self._no_judge
        btn = self.query_one("#run-nojudge-btn", Button)
        if self._no_judge:
            btn.add_class("toggled")
        else:
            btn.remove_class("toggled")

    @on(Button.Pressed, "#run-go")
    def _press_run(self) -> None:
        sel_text = self.query_one("#run-models-input", Input).value.strip()
        prompt = self.query_one("#run-prompt-input", Input).value.strip()

        if not prompt:
            self.query_one("#run-footer", Static).update("  Please enter a prompt!")
            return

        if sel_text.lower() == "all":
            specs = [m.spec for m in self._available]
        else:
            indices = []
            for part in sel_text.split(","):
                p = part.strip()
                if p.isdigit():
                    idx = int(p) - 1
                    if 0 <= idx < len(self._available):
                        indices.append(idx)
            specs = [self._available[i].spec for i in indices]

        if not specs:
            self.query_one("#run-footer", Static).update("  Select at least one model!")
            return

        self.query_one("#run-form").display = False
        self.query_one("#run-progress").display = True
        self._progress_data = {s: {"tokens": 0, "tps": 0.0, "status": "waiting"} for s in specs}
        self._refresh_progress(prompt)
        self.query_one("#run-footer", Static).update("  Running comparison...")

        self._do_run(specs, prompt)

    def _refresh_progress(self, prompt: str = "") -> None:
        t = Text()
        if prompt:
            t.append(f'  "{prompt}"\n\n', style=f"italic {_MUTED}")

        for model, data in self._progress_data.items():
            status = data.get("status", "waiting")
            tokens = data.get("tokens", 0)
            tps = data.get("tps", 0.0)

            if status == "done":
                icon = "\u2713"
                style = _SAGE
            elif status == "running":
                icon = "\u25b8"
                style = _BRONZE
            elif status == "error":
                icon = "\u2717"
                style = _TERRA
            else:
                icon = "\u25cb"
                style = _MUTED

            t.append(f"  {icon} ", style=style)
            t.append(f"{model:<24}", style=f"bold {style}")

            bar_w = 20
            if status == "running" and tokens > 0:
                filled = min(tokens // 5, bar_w)
                bar = "\u2588" * filled + "\u2591" * (bar_w - filled)
                t.append(f" {bar} ", style=_BRONZE)
            elif status == "done":
                bar = "\u2588" * bar_w
                t.append(f" {bar} ", style=_SAGE)
            else:
                bar = "\u2591" * bar_w
                t.append(f" {bar} ", style=_MUTED)

            t.append(f" {tokens} tok", style=_MUTED)
            if tps > 0:
                t.append(f"  {tps:.1f} tok/s", style=f"bold {_TEXT}")
            t.append("\n")

        self.query_one("#run-progress", Static).update(t)

    @work(thread=True)
    def _do_run(self, specs: list, prompt: str) -> None:
        import asyncio
        from gauntlet.core.runner import run_comparison, run_single_model
        from gauntlet.core.judge import judge_comparison
        from gauntlet.core.metrics import (
            ComparisonResult, compute_composite_scores, ScoreWeights, weights_for_category,
        )
        from gauntlet.core.leaderboard import Leaderboard
        from gauntlet.core.prompt_classifier import classify_prompt_detailed
        from gauntlet.core.recommendation import generate_recommendation
        from datetime import datetime, timezone

        def on_token(model: str, text: str, metrics):
            self._progress_data[model] = {
                "tokens": metrics.total_tokens,
                "tps": metrics.tokens_per_sec or 0.0,
                "status": "running",
            }
            self.app.call_from_thread(self._refresh_progress, prompt)

        try:
            if self._seq:
                all_metrics = []
                for spec in specs:
                    self._progress_data[spec]["status"] = "running"
                    self.app.call_from_thread(self._refresh_progress, prompt)

                    metrics = asyncio.run(run_single_model(
                        model_spec=spec, prompt=prompt, on_token=on_token,
                    ))
                    all_metrics.append(metrics)

                    self._progress_data[spec] = {
                        "tokens": metrics.total_tokens,
                        "tps": metrics.tokens_per_sec or 0.0,
                        "status": "done",
                    }
                    self.app.call_from_thread(self._refresh_progress, prompt)

                result = ComparisonResult(
                    prompt=prompt, models=all_metrics,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            else:
                for s in specs:
                    self._progress_data[s]["status"] = "running"
                self.app.call_from_thread(self._refresh_progress, prompt)

                result = asyncio.run(run_comparison(
                    model_specs=specs, prompt=prompt, on_token=on_token,
                ))
                for m in result.models:
                    self._progress_data[m.model] = {
                        "tokens": m.total_tokens,
                        "tps": m.tokens_per_sec or 0.0,
                        "status": "done" if not m.output.startswith("[ERROR]") else "error",
                    }
                self.app.call_from_thread(self._refresh_progress, prompt)

            # Classify prompt for domain-aware evaluation
            classification = classify_prompt_detailed(prompt)

            if not self._no_judge and len(specs) > 1:
                judge_label = "Judging quality"
                if classification.subcategory:
                    judge_label = f"Judging {classification.subcategory_label} quality"
                self.app.call_from_thread(
                    self._update_footer, f"  {judge_label}..."
                )
                result = asyncio.run(judge_comparison(
                    result, judge_model="auto", classification=classification,
                ))

            has_quality = not self._no_judge and len(specs) > 1
            category_weights = weights_for_category(classification.subcategory)
            result.scoring = compute_composite_scores(
                result, weights=category_weights, has_quality=has_quality,
            )
            result.winner = result.scoring.winner if result.scoring else None
            result.classification = classification
            result.recommendation = generate_recommendation(result)

            if len(specs) > 1:
                lb = Leaderboard()
                lb.update_from_comparison(result)

            self._comparison_result = result
            self.app.call_from_thread(self._show_results, result)

        except Exception as e:
            self.app.call_from_thread(self._show_run_error, str(e))

    def _update_footer(self, msg: str) -> None:
        self.query_one("#run-footer", Static).update(msg)

    def _show_run_error(self, msg: str) -> None:
        t = Text()
        t.append(f"\n  Error: {msg}\n", style=f"bold {_TERRA}")
        self.query_one("#run-results", Static).update(t)
        self.query_one("#run-results").display = True
        self.query_one("#run-done-buttons").display = True
        self.query_one("#run-footer", Static).update("  Error occurred  |  ESC back")

    def _show_results(self, result) -> None:
        t = Text()
        t.append("\n  RESULTS\n", style=f"bold {_BRONZE}")
        t.append("  " + "\u2500" * 50 + "\n", style=_BORDER)

        colors = [_STEEL, _BRONZE, _SAGE, _GOLD, _MAUVE, _TEAL]

        for i, m in enumerate(result.models):
            color = colors[i % len(colors)]
            is_winner = result.winner and m.model == result.winner
            badge = " \u2605 WINNER" if is_winner else ""
            badge_style = f"bold {_SAGE}" if is_winner else ""

            t.append(f"\n  {m.model}", style=f"bold {color}")
            if badge:
                t.append(badge, style=badge_style)
            t.append("\n")

            if m.tokens_per_sec:
                t.append(f"    Speed: {m.tokens_per_sec:.1f} tok/s\n", style=_TEXT)
            if m.ttft_ms:
                t.append(f"    TTFT: {m.ttft_ms:.0f}ms\n", style=_TEXT)
            if m.total_tokens:
                t.append(f"    Tokens: {m.total_tokens}\n", style=_MUTED)
            if m.total_time_s:
                t.append(f"    Time: {m.total_time_s:.1f}s\n", style=_MUTED)
            if m.overall_score:
                t.append(f"    Quality: {m.overall_score:.1f}/10\n", style=_TEXT)
            if m.peak_memory_delta_mb is not None:
                t.append(f"    RAM delta: {m.peak_memory_delta_mb:+.0f}MB\n", style=_MUTED)

        if result.scoring:
            t.append(f"\n  Formula: {result.scoring.formula}\n", style=_MUTED)
            t.append("\n")

            for ms in result.scoring.model_scores:
                is_w = ms.rank == 1
                style = f"bold {_SAGE}" if is_w else _TEXT
                t.append(f"  #{ms.rank} ", style=_MUTED)
                t.append(f"{ms.model}", style=style)
                t.append(f"  composite: {ms.composite:.3f}\n", style=_MUTED)
                for c in ms.components:
                    rank_style = _SAGE if c.rank == 1 else _MUTED
                    t.append(f"      {c.metric_name}: ", style=_MUTED)
                    t.append(f"{c.raw_value:.1f} {c.raw_unit}", style=rank_style)
                    t.append(f"  (w: {c.weighted:.3f})\n", style=_MUTED)

            if result.scoring.winner_reason:
                t.append(f"\n  {result.scoring.winner_reason}\n", style=f"italic {_KHAKI}")

        self.query_one("#run-progress").display = False
        self.query_one("#run-results", Static).update(t)
        self.query_one("#run-results").display = True
        self.query_one("#run-done-buttons").display = True
        self.query_one("#run-footer", Static).update("  Done  |  ESC back")

    @on(Button.Pressed, "#run-again")
    def _press_again(self) -> None:
        self.query_one("#run-results").display = False
        self.query_one("#run-done-buttons").display = False
        self.query_one("#run-progress").display = False
        self.query_one("#run-form").display = True
        self.query_one("#run-footer", Static).update(
            "  Pick models, enter prompt, press Run  |  ESC back"
        )

    @on(Button.Pressed, "#run-back-btn")
    def _press_back(self) -> None:
        self.dismiss()

    def action_go_back(self) -> None:
        self.dismiss()


# ---------------------------------------------------------------------------
# BenchmarkScreen - Behavioral test suite
# ---------------------------------------------------------------------------


class BenchmarkScreen(Screen):
    """Gauntlet behavioral test: pick model, run modules, see trust score."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]

    DEFAULT_CSS = f"""
    BenchmarkScreen {{
        background: {_BG};
    }}
    #bench-header {{
        text-align: center;
        height: 3;
        padding: 1 0;
        color: {_SAGE};
        text-style: bold;
    }}
    #bench-body {{
        height: 1fr;
        margin: 0 2;
        overflow-y: auto;
    }}
    #bench-model-list {{
        height: auto;
        margin: 0 0 1 0;
    }}
    #bench-form {{
        height: auto;
        margin: 1 0;
    }}
    .bench-label {{
        height: 1;
        margin: 1 0 0 0;
        color: {_MUTED};
    }}
    #bench-models-input {{
        margin: 0 0 1 0;
    }}
    #bench-options {{
        height: auto;
        margin: 1 0;
    }}
    .bench-opt-btn {{
        width: auto;
        min-width: 16;
        margin: 0 1 0 0;
        height: 3;
        background: {_CARD};
        color: {_MUTED};
        border: tall {_BORDER};
    }}
    .bench-opt-btn.toggled {{
        background: #101a14;
        color: {_SAGE};
        border: tall {_SAGE};
    }}
    #bench-go {{
        width: auto;
        min-width: 20;
        height: 3;
        margin: 1 0;
        background: #101a14;
        color: {_SAGE};
        border: tall {_SAGE};
    }}
    #bench-go:hover, #bench-go:focus {{
        background: #182a1e;
        border: tall {_SAGE};
    }}
    #bench-progress {{
        height: auto;
        margin: 1 0;
    }}
    #bench-results {{
        height: auto;
        margin: 1 0;
    }}
    #bench-done-buttons {{
        height: auto;
        margin: 1 0;
    }}
    #bench-again {{
        width: auto;
        min-width: 16;
        height: 3;
        margin: 0 1 0 0;
        background: #101a14;
        color: {_SAGE};
        border: tall {_SAGE};
    }}
    #bench-back-btn {{
        width: auto;
        min-width: 16;
        height: 3;
        background: {_CARD};
        color: {_MUTED};
        border: tall {_BORDER};
    }}
    #bench-footer {{
        dock: bottom;
        height: 1;
        background: {_CARD};
        padding: 0 2;
        color: {_MUTED};
    }}
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._available = []
        self._quick = False
        self._progress_lines = []

    def compose(self) -> ComposeResult:
        yield Static("BEHAVIORAL RELIABILITY TEST", id="bench-header")
        yield Container(
            Static("Scanning for models...", id="bench-model-list"),
            Container(
                Static("Select model (number):", classes="bench-label"),
                Input(placeholder="e.g. 1", id="bench-models-input"),
                Horizontal(
                    Button("Quick Mode", id="bench-quick-btn", classes="bench-opt-btn"),
                    id="bench-options",
                ),
                Button("Run Gauntlet", id="bench-go"),
                id="bench-form",
            ),
            Static("", id="bench-progress"),
            Static("", id="bench-results"),
            Horizontal(
                Button("Run Again", id="bench-again"),
                Button("Back to Menu", id="bench-back-btn"),
                id="bench-done-buttons",
            ),
            id="bench-body",
        )
        yield Static("  Loading models...  |  ESC back", id="bench-footer")

    def on_mount(self) -> None:
        self.query_one("#bench-form").display = False
        self.query_one("#bench-progress").display = False
        self.query_one("#bench-results").display = False
        self.query_one("#bench-done-buttons").display = False
        self._fetch_models()

    @work(thread=True)
    def _fetch_models(self) -> None:
        import asyncio
        from gauntlet.core.discover import discover_ollama

        try:
            models = asyncio.run(discover_ollama())
            self.app.call_from_thread(self._show_models, models)
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))

    def _show_models(self, models) -> None:
        self._available = models
        ml = self.query_one("#bench-model-list", Static)

        if not models:
            ml.update(Text("  No models found. Is Ollama running?", style=_GOLD))
            self.query_one("#bench-footer", Static).update("  No models  |  ESC back")
            return

        t = Text()
        t.append("  Available Models:\n", style=f"bold {_TEXT}")
        for i, m in enumerate(models, 1):
            size = f"{m.size_gb}GB" if m.size_gb else "?"
            params = m.parameter_size or ""
            t.append(f"   {i}. ", style=_SAGE)
            t.append(f"{m.name}", style=f"bold {_TEXT}")
            t.append(f"  {size} {params}\n", style=_MUTED)

        # Show available modules
        from gauntlet.core.module_runner import load_all_modules, list_modules as _list_mods
        load_all_modules()
        mods = _list_mods()
        if mods:
            t.append("\n  Modules:\n", style=f"bold {_MUTED}")
            for m in mods:
                qp = m.build_probes(quick=True)
                fp = m.build_probes(quick=False)
                t.append(f"    {m.name}", style=_STEEL)
                t.append(f"  {len(fp)} probes ({len(qp)} quick)\n", style=_MUTED)

        ml.update(t)
        self.query_one("#bench-models-input", Input).value = "1"
        self.query_one("#bench-form").display = True
        self.query_one("#bench-footer", Static).update(
            "  Select model number, press Run Gauntlet  |  ESC back"
        )

    def _show_error(self, msg: str) -> None:
        self.query_one("#bench-model-list", Static).update(
            Text(f"  Error: {msg}", style=_TERRA)
        )

    @on(Button.Pressed, "#bench-quick-btn")
    def _toggle_quick(self) -> None:
        self._quick = not self._quick
        btn = self.query_one("#bench-quick-btn", Button)
        if self._quick:
            btn.add_class("toggled")
        else:
            btn.remove_class("toggled")

    @on(Button.Pressed, "#bench-go")
    def _press_go(self) -> None:
        sel_text = self.query_one("#bench-models-input", Input).value.strip()

        if not sel_text or not sel_text.isdigit():
            self.query_one("#bench-footer", Static).update("  Enter a model number!")
            return

        idx = int(sel_text) - 1
        if idx < 0 or idx >= len(self._available):
            self.query_one("#bench-footer", Static).update("  Invalid model number!")
            return

        model = self._available[idx]

        self.query_one("#bench-form").display = False
        self.query_one("#bench-progress").display = True

        self._progress_lines = []
        mode = "quick" if self._quick else "full"
        self._progress_lines.append(
            f"  Running Gauntlet on {model.name} ({mode} mode)\n"
        )
        self._progress_lines.append(
            "  Deterministic scoring, no LLM judge\n\n"
        )
        self._refresh_progress()
        self.query_one("#bench-footer", Static).update(
            "  Gauntlet running (thinking models take 2-5 min per probe)..."
        )

        self._do_gauntlet(model.name)

    def _refresh_progress(self) -> None:
        t = Text()
        for line in self._progress_lines:
            if "PASS" in line:
                parts = line.split("PASS", 1)
                t.append(parts[0])
                t.append("PASS", style=_SAGE)
                if len(parts) > 1:
                    t.append(parts[1])
            elif "FAIL" in line:
                parts = line.split("FAIL", 1)
                t.append(parts[0])
                t.append("FAIL", style=_TERRA)
                if len(parts) > 1:
                    t.append(parts[1])
            elif line.startswith("  Running"):
                t.append(line, style=f"bold {_BRONZE}")
            elif "Deterministic" in line:
                t.append(line, style=_MUTED)
            else:
                t.append(line, style=_STEEL)
        self.query_one("#bench-progress", Static).update(t)

    @work(thread=True)
    def _do_gauntlet(self, model_name: str) -> None:
        import asyncio
        from gauntlet.core.module_runner import run_gauntlet

        def on_progress(mod_name, current, total, status):
            self.app.call_from_thread(
                self._add_progress,
                f"  {mod_name}  [{current}/{total}]  {status}\n",
            )

        def on_probe(idx, total, name, passed):
            icon = "PASS" if passed else "FAIL"
            self.app.call_from_thread(
                self._add_progress,
                f"    [{idx}/{total}]  {icon}  {name}\n",
            )

        try:
            results, score = asyncio.run(run_gauntlet(
                model_name=model_name,
                provider="ollama",
                profile="assistant",
                quick=self._quick,
                config={"on_probe_complete": on_probe},
                on_progress=on_progress,
            ))
            self.app.call_from_thread(self._show_gauntlet_results, model_name, results, score)

        except Exception as e:
            self.app.call_from_thread(self._show_bench_error, str(e))

    def _add_progress(self, line: str) -> None:
        self._progress_lines.append(line)
        self._refresh_progress()

    def _show_bench_error(self, msg: str) -> None:
        t = Text()
        t.append(f"\n  Error: {msg}\n", style=f"bold {_TERRA}")
        self.query_one("#bench-results", Static).update(t)
        self.query_one("#bench-progress").display = False
        self.query_one("#bench-results").display = True
        self.query_one("#bench-done-buttons").display = True
        self.query_one("#bench-footer", Static).update("  Error  |  ESC back")

    def _show_gauntlet_results(self, model_name, results, score) -> None:
        t = Text()
        t.append("\n  TRUST REPORT\n", style=f"bold {_BRONZE}")
        t.append("  " + "\u2500" * 50 + "\n\n", style=_BORDER)

        grade_colors = {
            "A": f"bold {_SAGE}", "B": _SAGE, "C": _GOLD,
            "D": _TERRA, "F": f"bold {_TERRA}",
        }
        grade_style = grade_colors.get(score.overall_grade, _TEXT)

        t.append(f"  {model_name}", style=f"bold {_TEXT}")
        t.append(f"  Grade: ", style=_MUTED)
        t.append(f"{score.overall_grade}", style=grade_style)
        t.append(f"  ({score.overall_score:.0%})", style=_TEXT)
        t.append(f"  {score.passed_probes}/{score.total_probes} probes passed\n\n", style=_MUTED)

        if score.critical_failures > 0:
            t.append(
                f"  {score.critical_failures} CRITICAL FAILURE(S)\n\n",
                style=f"bold {_TERRA}",
            )

        for ms in score.module_scores:
            mg_style = grade_colors.get(ms.grade, _TEXT)

            bar_w = 20
            filled = int(ms.score * bar_w)
            bar_filled = "\u2588" * filled
            bar_empty = "\u2591" * (bar_w - filled)
            bar_style = _SAGE if ms.score >= 0.7 else _GOLD if ms.score >= 0.4 else _TERRA

            t.append(f"  ", style=_TEXT)
            t.append(f"{ms.grade}", style=mg_style)
            t.append(f"  {ms.module_name:<24}", style=_TEXT)
            t.append(bar_filled, style=bar_style)
            t.append(bar_empty, style=_MUTED)
            t.append(f"  {ms.score:.0%}", style=bar_style)
            t.append(f"  ({ms.passed}/{ms.total})\n", style=_MUTED)

            for r in results:
                if r.module_name == ms.module_name:
                    for pr in r.probe_results:
                        if not pr.passed:
                            sev_colors = {
                                "critical": f"bold {_TERRA}", "high": _TERRA,
                                "medium": _GOLD, "low": _MUTED,
                            }
                            sev_style = sev_colors.get(pr.severity.value, _MUTED)
                            t.append(f"      ", style=_TEXT)
                            t.append("FAIL", style=sev_style)
                            t.append(f"  {pr.probe_name}", style=_TEXT)
                            t.append(f"  {pr.reason}\n", style=_MUTED)

        t.append("\n")
        t.append(f"  {score.summary}\n", style=_MUTED)

        self.query_one("#bench-progress").display = False
        self.query_one("#bench-results", Static).update(t)
        self.query_one("#bench-results").display = True
        self.query_one("#bench-done-buttons").display = True
        self.query_one("#bench-footer", Static).update("  Gauntlet complete  |  ESC back")

    @on(Button.Pressed, "#bench-again")
    def _press_again(self) -> None:
        self.query_one("#bench-results").display = False
        self.query_one("#bench-done-buttons").display = False
        self.query_one("#bench-form").display = True
        self.query_one("#bench-footer", Static).update(
            "  Select model, press Run Gauntlet  |  ESC back"
        )

    @on(Button.Pressed, "#bench-back-btn")
    def _press_back(self) -> None:
        self.dismiss()

    def action_go_back(self) -> None:
        self.dismiss()


# ---------------------------------------------------------------------------
# DashboardScreen - Web dashboard launcher
# ---------------------------------------------------------------------------


class DashboardScreen(Screen):
    """Launches the web dashboard and shows server status."""

    BINDINGS = [
        Binding("escape", "stop_server", "Stop & Back"),
        Binding("q", "stop_server", "Stop & Back"),
    ]

    DEFAULT_CSS = f"""
    DashboardScreen {{
        background: {_BG};
    }}
    #dash-header {{
        text-align: center;
        height: 3;
        padding: 1 0;
        color: {_BRONZE};
        text-style: bold;
    }}
    #dash-body {{
        height: 1fr;
        margin: 0 2;
        overflow-y: auto;
    }}
    #dash-status {{
        height: auto;
        margin: 1 0;
    }}
    #dash-events {{
        height: auto;
        margin: 1 0;
    }}
    #dash-footer {{
        dock: bottom;
        height: 1;
        background: {_CARD};
        padding: 0 2;
        color: {_MUTED};
    }}
    """

    def __init__(self, port: int = 7878, **kwargs):
        super().__init__(**kwargs)
        self._port = port
        self._client_count = 0
        self._status = "Starting..."
        self._events: list[tuple[str, str]] = []
        self._server_task = None
        self._stopping = False

    def compose(self) -> ComposeResult:
        yield Static("DASHBOARD", id="dash-header")
        yield Container(
            Static("Starting server...", id="dash-status"),
            Static("", id="dash-events"),
            id="dash-body",
        )
        yield Static("  Starting...  |  ESC stop & back", id="dash-footer")

    def on_mount(self) -> None:
        self._start_server()

    def _on_client_change(self, count: int) -> None:
        self._client_count = count
        if count > 0:
            self._status = "Connected"
        else:
            self._status = "Waiting for browser..."
        self.app.call_from_thread(self._refresh_display)

    def _on_event(self, msg: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._events.append((timestamp, msg))
        if len(self._events) > 30:
            self._events = self._events[-30:]

        if "Shutting down" in msg and "Shutting down in" not in msg:
            self._status = "Shutting down..."
        elif "Auto-shutdown cancelled" in msg:
            self._status = "Connected"
        elif "Server starting" in msg or "started" in msg.lower():
            self._status = "Running"

        self.app.call_from_thread(self._refresh_display)

    def _refresh_display(self) -> None:
        st = Text()
        if self._status == "Connected":
            st.append("  \u25cf ", style=f"bold {_SAGE}")
            st.append(self._status, style=_SAGE)
        elif "Waiting" in self._status or self._status == "Running":
            st.append("  \u25cf ", style=f"bold {_GOLD}")
            st.append(self._status, style=_GOLD)
        elif "Shutting" in self._status:
            st.append("  \u25cf ", style=f"bold {_TERRA}")
            st.append(self._status, style=_TERRA)
        else:
            st.append("  \u25cf ", style=f"bold {_BRONZE}")
            st.append(self._status, style=_BRONZE)

        st.append(f"    http://127.0.0.1:{self._port}", style=f"bold underline {_BRONZE}")

        if self._client_count > 0:
            suffix = "s" if self._client_count != 1 else ""
            st.append(f"    {self._client_count} client{suffix}", style=_SAGE)

        st.append("\n")
        self.query_one("#dash-status", Static).update(st)

        ev = Text()
        for ts, msg in self._events[-15:]:
            ev.append(f"  {ts} ", style=_MUTED)
            if "error" in msg.lower():
                ev.append(msg, style=_TERRA)
            elif "connected" in msg.lower() and "dis" not in msg.lower():
                ev.append(msg, style=_SAGE)
            elif "disconnected" in msg.lower():
                ev.append(msg, style=_GOLD)
            elif "shutdown" in msg.lower():
                ev.append(msg, style=f"bold {_TERRA}")
            else:
                ev.append(msg, style=_TEXT)
            ev.append("\n")

        self.query_one("#dash-events", Static).update(ev)
        self.query_one("#dash-footer", Static).update(
            f"  {self._status}  |  ESC stop & back  |  Auto-shutdown 15s after last disconnect"
        )

    @work(thread=True)
    def _start_server(self) -> None:
        import asyncio
        import webbrowser
        import threading

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            from gauntlet.dashboard.server import start_server

            threading.Timer(
                1.5, lambda: webbrowser.open(f"http://127.0.0.1:{self._port}")
            ).start()

            loop.run_until_complete(start_server(
                model_specs=[],
                prompt="",
                port=self._port,
                on_client_change=self._on_client_change,
                on_event=self._on_event,
                auto_shutdown=True,
            ))
        except Exception as e:
            self._on_event(f"Server error: {e}")
        finally:
            self.app.call_from_thread(self._server_stopped)

    def _server_stopped(self) -> None:
        self._status = "Stopped"
        self._refresh_display()
        if not self._stopping:
            self.query_one("#dash-footer", Static).update(
                "  Server stopped  |  ESC back"
            )

    def action_stop_server(self) -> None:
        self._stopping = True
        self.dismiss()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class GauntletApp(App):
    """The Gauntlet TUI -- professional behavioral reliability benchmark."""

    TITLE = "Gauntlet"

    CSS = f"""
    Screen {{
        background: {_BG};
    }}

    #root {{
        height: 100%;
    }}

    #header-area {{
        height: auto;
        padding: 1 2 0 2;
    }}

    #logo {{
        height: auto;
    }}

    #tagline {{
        height: 1;
        color: {_MUTED};
        margin: 0 0 0 1;
    }}

    #scan-bar {{
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        content-align: left middle;
        padding: 0 2;
    }}

    #main-row {{
        height: 1fr;
        padding: 1 2 0 2;
    }}

    #menu-panel {{
        width: 40;
        padding: 0 2 0 0;
    }}

    .menu-btn {{
        width: 100%;
        margin: 0 0 1 0;
        height: 3;
    }}

    #btn-run {{
        background: #1a1510;
        color: {_BRONZE};
        border: tall {_KHAKI};
    }}
    #btn-run:hover, #btn-run:focus {{
        background: #2a2018;
        border: tall {_BRONZE};
    }}

    #btn-dashboard {{
        background: #1a1510;
        color: {_BRONZE};
        border: tall {_KHAKI};
    }}
    #btn-dashboard:hover, #btn-dashboard:focus {{
        background: #2a2018;
        border: tall {_BRONZE};
    }}

    #btn-benchmark {{
        background: #101a14;
        color: {_SAGE};
        border: tall #1a2a1e;
    }}
    #btn-benchmark:hover, #btn-benchmark:focus {{
        background: #182a1e;
        border: tall {_SAGE};
    }}

    #btn-leaderboard, #btn-discover {{
        background: {_CARD};
        color: {_MUTED};
        border: tall {_BORDER};
    }}
    #btn-leaderboard:hover, #btn-discover:hover,
    #btn-leaderboard:focus, #btn-discover:focus {{
        background: {_BORDER};
        color: {_TEXT};
        border: tall #333;
    }}

    #info-panel {{
        width: 1fr;
        padding: 0 0 0 1;
        border-left: solid {_BORDER};
    }}

    #status-bar {{
        dock: bottom;
        height: 1;
        background: {_CARD};
        padding: 0 1;
        color: {_MUTED};
    }}

    #footer-hint {{
        dock: bottom;
        height: 1;
        background: {_BG};
        text-align: center;
        color: #2a2a30;
    }}
    """

    BINDINGS = [
        Binding("1", "menu_run", "Compare", show=False),
        Binding("2", "menu_dashboard", "Dashboard", show=False),
        Binding("3", "menu_benchmark", "Benchmark", show=False),
        Binding("4", "menu_leaderboard", "Leaderboard", show=False),
        Binding("5", "menu_discover", "Discover", show=False),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._system_info = SystemInfo(id="system-info")

    def compose(self) -> ComposeResult:
        yield Container(
            Container(
                AnimatedLogo(id="logo"),
                Static(
                    "Behavioral reliability under pressure.",
                    id="tagline",
                ),
                id="header-area",
            ),
            ScanBar(id="scan-bar"),
            Horizontal(
                Vertical(
                    Button(
                        "1  Compare Models",
                        id="btn-run",
                        classes="menu-btn",
                    ),
                    Button(
                        "2  Web Dashboard",
                        id="btn-dashboard",
                        classes="menu-btn",
                    ),
                    Button(
                        "3  Run Gauntlet",
                        id="btn-benchmark",
                        classes="menu-btn",
                    ),
                    Button(
                        "4  Leaderboard",
                        id="btn-leaderboard",
                        classes="menu-btn",
                    ),
                    Button(
                        "5  Discover Models",
                        id="btn-discover",
                        classes="menu-btn",
                    ),
                    id="menu-panel",
                ),
                self._system_info,
                id="main-row",
            ),
            id="root",
        )
        yield Static(
            "q quit  |  1-5 select  |  arrows navigate  |  enter confirm",
            id="footer-hint",
        )
        yield Static("", id="status-bar")

    def on_mount(self) -> None:
        self._discover_models()
        self._check_update()

    @work(thread=True)
    def _check_update(self) -> None:
        """Update check in worker thread. Waits up to 5s for PyPI on first run."""
        try:
            from gauntlet.core.update_check import check_for_update, get_update_message
            # Use blocking=True since we're already in a worker thread.
            # This ensures first-run users see the notice (no stale cache yet).
            latest = check_for_update(blocking=True, timeout=5.0)
            if latest:
                from gauntlet import __version__
                msg = (
                    f"Update available: v{__version__} \u2192 v{latest}. "
                    f"Run: pipx upgrade gauntlet-cli"
                )
                self.app.call_from_thread(
                    self.query_one("#status-bar", Static).update,
                    f"[yellow]{msg}[/yellow]",
                )
        except Exception:
            pass

    @work(thread=True)
    def _discover_models(self) -> None:
        import httpx

        try:
            resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                model_list = []
                for m in models:
                    details = m.get("details", {})
                    size_bytes = m.get("size", 0)
                    size_gb = (
                        round(size_bytes / (1024**3), 1) if size_bytes else None
                    )
                    model_list.append(
                        {
                            "name": m.get("name", "?"),
                            "size_gb": size_gb,
                            "parameter_size": details.get("parameter_size", ""),
                        }
                    )

                self.call_from_thread(self._system_info.set_models, model_list)
            else:
                self.call_from_thread(self._system_info.set_error)
        except Exception:
            self.call_from_thread(self._system_info.set_error)

    # ---- Button handlers ----

    @on(Button.Pressed, "#btn-run")
    def _press_run(self) -> None:
        self.push_screen(RunScreen())

    @on(Button.Pressed, "#btn-dashboard")
    def _press_dashboard(self) -> None:
        self.push_screen(DashboardScreen())

    @on(Button.Pressed, "#btn-benchmark")
    def _press_benchmark(self) -> None:
        self.push_screen(BenchmarkScreen())

    @on(Button.Pressed, "#btn-leaderboard")
    def _press_leaderboard(self) -> None:
        self.push_screen(LeaderboardScreen())

    @on(Button.Pressed, "#btn-discover")
    def _press_discover(self) -> None:
        self.push_screen(DiscoverScreen())

    # ---- Key bindings ----

    def action_menu_run(self) -> None:
        self.push_screen(RunScreen())

    def action_menu_dashboard(self) -> None:
        self.push_screen(DashboardScreen())

    def action_menu_benchmark(self) -> None:
        self.push_screen(BenchmarkScreen())

    def action_menu_leaderboard(self) -> None:
        self.push_screen(LeaderboardScreen())

    def action_menu_discover(self) -> None:
        self.push_screen(DiscoverScreen())


# ---------------------------------------------------------------------------
# Server TUI (Rich Live, for when dashboard is running via CLI)
# ---------------------------------------------------------------------------


class ServerTUI:
    """Rich Live display for when the dashboard server is running."""

    def __init__(self, port: int = 7878, models=None, prompt="", sequential=False):
        self.port = port
        self.models = models or []
        self.prompt = prompt
        self.sequential = sequential
        self.client_count = 0
        self.status = "Starting..."
        self.events: deque[tuple[str, str]] = deque(maxlen=30)
        self._live = None

    def on_client_change(self, count: int) -> None:
        self.client_count = count
        self.status = "Connected" if count > 0 else "Waiting for browser..."
        self._refresh()

    def on_event(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.events.append((timestamp, message))
        if "Shutting down" in message and "Shutting down in" not in message:
            self.status = "Shutting down..."
        elif "Auto-shutdown cancelled" in message:
            self.status = "Connected"
        elif "Server starting" in message:
            self.status = "Running"
        self._refresh()

    def _refresh(self) -> None:
        if self._live:
            try:
                self._live.update(self._build())
            except Exception:
                pass

    def _build(self):
        from rich.console import Group

        parts = []

        if self.status == "Connected":
            dot, st = f"[bold {_SAGE}]\u25cf[/]", f"[{_SAGE}]{self.status}[/]"
        elif "Waiting" in self.status or self.status == "Running":
            dot, st = f"[bold {_GOLD}]\u25cf[/]", f"[{_GOLD}]{self.status}[/]"
        elif "Shutting" in self.status:
            dot, st = f"[bold {_TERRA}]\u25cf[/]", f"[{_TERRA}]{self.status}[/]"
        else:
            dot, st = f"[bold {_BRONZE}]\u25cf[/]", f"[{_BRONZE}]{self.status}[/]"

        info = (
            f"  {dot} {st}  "
            f"[bold underline {_BRONZE}]http://127.0.0.1:{self.port}[/]"
        )
        if self.client_count > 0:
            info += (
                f"  [{_SAGE}]{self.client_count}[/]"
                f" [dim]client{'s' if self.client_count != 1 else ''}[/]"
            )
        parts.append(
            Panel(
                Text.from_markup(info),
                title=f"[bold {_TEXT}] GAUNTLET [/]",
                title_align="left",
                border_style=_BRONZE,
                padding=(0, 1),
            )
        )

        if self.events:
            parts.append(Text(""))
            for ts, msg in list(self.events)[-12:]:
                line = Text()
                line.append(f"  {ts} ", style="dim")
                if "error" in msg.lower():
                    line.append(msg, style=_TERRA)
                elif "connected" in msg.lower() and "dis" not in msg.lower():
                    line.append(msg, style=_SAGE)
                elif "disconnected" in msg.lower():
                    line.append(msg, style=_GOLD)
                elif "shutdown" in msg.lower():
                    line.append(msg, style=f"bold {_TERRA}")
                elif (
                    "cancelled" in msg.lower()
                    or "browser" in msg.lower()
                    or "starting" in msg.lower()
                ):
                    line.append(msg, style=_BRONZE)
                else:
                    line.append(msg, style=_TEXT)
                parts.append(line)

        parts.append(Text(""))
        f = Text()
        f.append("  Ctrl+C", style=f"bold {_BRONZE}")
        f.append(" quit  |  ", style="dim")
        f.append("Auto-shutdown", style=f"bold {_BRONZE}")
        f.append(" 15s after last browser disconnects", style="dim")
        parts.append(f)

        return Group(*parts)

    async def run_with_server(self, server_coro) -> None:
        from rich.console import Console, Group
        from rich.live import Live
        from rich.rule import Rule

        console = Console()
        console.print()
        console.print(Rule(f"[bold {_BRONZE}] GAUNTLET Dashboard [/]", style=_BRONZE))
        console.print()

        tbl = Table(show_header=False, box=None, padding=(0, 1))
        tbl.add_column("", style="dim", width=10)
        tbl.add_column("")
        tbl.add_row(
            "URL",
            f"[bold underline {_BRONZE}]http://127.0.0.1:{self.port}[/]",
        )
        if self.models:
            tbl.add_row(
                "Models",
                ", ".join(f"[{_STEEL}]{m}[/]" for m in self.models),
            )
        if self.prompt:
            tbl.add_row("Prompt", self.prompt[:80])
        tbl.add_row("Mode", "Sequential" if self.sequential else "Parallel")
        console.print(tbl)
        console.print()

        self.on_event("Gauntlet server started")

        with Live(
            self._build(),
            console=console,
            refresh_per_second=4,
            transient=False,
        ) as live:
            self._live = live
            try:
                await server_coro
            except (KeyboardInterrupt, SystemExit):
                self.on_event("Interrupted by user")
            except Exception as e:
                self.on_event(f"Error: {e}")
            finally:
                self._live = None

        console.print()
        console.print(f"[dim]Gauntlet dashboard stopped.[/dim]")
        console.print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_tui() -> Optional[str]:
    """Launch the Gauntlet TUI. Returns the selected action or None."""
    app = GauntletApp()
    return app.run()
