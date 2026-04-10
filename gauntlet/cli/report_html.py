"""HTML Report Generator -- self-contained HTML with inline SVG charts.

Generates a single HTML file with:
  - Radar chart of trust dimensions (SVG)
  - Deduction waterfall chart (SVG)
  - Probe detail accordion (vanilla JS)
  - All CSS/JS inline (no external dependencies)
"""

from __future__ import annotations

import html
import math
from gauntlet.core.trust_score import TrustScore, _MODULE_DEDUCTION_CAP
from gauntlet.core.report import Finding, MODULE_LABELS
from gauntlet.core.modules.base import ModuleResult

# Short labels for chart axes (derived from MODULE_LABELS)
_SHORT_LABELS = {k: v.split()[0] if len(v) > 12 else v for k, v in MODULE_LABELS.items()}


def _generate_radar_svg(module_pass_rates: dict[str, float], size: int = 300) -> str:
    """Generate SVG radar chart of module pass rates."""
    modules = list(module_pass_rates.items())
    n = len(modules)
    if n < 3:
        return ""

    cx, cy = size // 2, size // 2
    radius = size // 2 - 40
    angle_step = 2 * math.pi / n

    # Background rings
    rings_svg = ""
    for r_frac in [0.25, 0.5, 0.75, 1.0]:
        r = radius * r_frac
        rings_svg += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#333" stroke-width="0.5" />\n'

    # Axis lines and labels
    axes_svg = ""
    for i, (mod_name, _) in enumerate(modules):
        angle = -math.pi / 2 + i * angle_step
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        axes_svg += f'<line x1="{cx}" y1="{cy}" x2="{x}" y2="{y}" stroke="#444" stroke-width="0.5" />\n'
        label = _SHORT_LABELS.get(mod_name, mod_name[:10])
        lx = cx + (radius + 20) * math.cos(angle)
        ly = cy + (radius + 20) * math.sin(angle)
        anchor = "middle"
        if math.cos(angle) > 0.3:
            anchor = "start"
        elif math.cos(angle) < -0.3:
            anchor = "end"
        axes_svg += f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" fill="#aaa" font-size="11">{html.escape(label)}</text>\n'

    # Data polygon
    points = []
    for i, (_, rate) in enumerate(modules):
        angle = -math.pi / 2 + i * angle_step
        r = radius * rate
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        points.append(f"{x},{y}")

    polygon_svg = f'<polygon points="{" ".join(points)}" fill="rgba(0, 212, 255, 0.2)" stroke="#00d4ff" stroke-width="2" />\n'

    # Data points
    dots_svg = ""
    for i, (_, rate) in enumerate(modules):
        angle = -math.pi / 2 + i * angle_step
        r = radius * rate
        x = cx + r * math.cos(angle)
        y = cy + r * math.sin(angle)
        dots_svg += f'<circle cx="{x}" cy="{y}" r="4" fill="#00d4ff" />\n'

    return (
        f'<svg width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">\n'
        f'{rings_svg}{axes_svg}{polygon_svg}{dots_svg}'
        f'</svg>'
    )


def _generate_waterfall_svg(trust: TrustScore, width: int = 500, height: int = 250) -> str:
    """Generate SVG waterfall chart showing deductions from 100."""
    deductions = [d for d in trust.deductions if d.deduction > 0]
    if not deductions:
        return ""

    # Group by module and cap
    module_deductions: dict[str, float] = {}
    for d in deductions:
        module_deductions[d.module_name] = module_deductions.get(d.module_name, 0) + d.deduction

    items = list(module_deductions.items())
    bar_width = min(60, (width - 80) // (len(items) + 2))
    x_start = 60
    y_top = 30
    y_bottom = height - 40
    chart_height = y_bottom - y_top
    scale = chart_height / 100

    bars_svg = ""
    running = 100.0

    # Starting bar (100)
    bh = running * scale
    bars_svg += (
        f'<rect x="{x_start}" y="{y_bottom - bh}" width="{bar_width}" height="{bh}" '
        f'fill="#10b981" rx="2" />\n'
        f'<text x="{x_start + bar_width // 2}" y="{y_bottom - bh - 5}" '
        f'text-anchor="middle" fill="#aaa" font-size="10">100</text>\n'
        f'<text x="{x_start + bar_width // 2}" y="{y_bottom + 15}" '
        f'text-anchor="middle" fill="#aaa" font-size="9">Start</text>\n'
    )

    for i, (mod_name, ded) in enumerate(items):
        capped = min(ded, _MODULE_DEDUCTION_CAP)
        x = x_start + (i + 1) * (bar_width + 10)
        old_running = running
        running -= capped

        # Deduction bar (red, hanging from previous level)
        bar_top = y_bottom - old_running * scale
        bar_h = capped * scale
        label = _SHORT_LABELS.get(mod_name, mod_name[:8])

        bars_svg += (
            f'<rect x="{x}" y="{bar_top}" width="{bar_width}" height="{bar_h}" '
            f'fill="#ef4444" rx="2" />\n'
            f'<text x="{x + bar_width // 2}" y="{bar_top - 5}" '
            f'text-anchor="middle" fill="#ef4444" font-size="10">-{capped:.0f}</text>\n'
            f'<text x="{x + bar_width // 2}" y="{y_bottom + 15}" '
            f'text-anchor="middle" fill="#aaa" font-size="8" transform="rotate(-30 {x + bar_width // 2} {y_bottom + 15})">{html.escape(label)}</text>\n'
        )

    # Final bar
    x_final = x_start + (len(items) + 1) * (bar_width + 10)
    final_h = max(running, 0) * scale
    final_color = "#10b981" if running >= 75 else "#f59e0b" if running >= 60 else "#ef4444"
    bars_svg += (
        f'<rect x="{x_final}" y="{y_bottom - final_h}" width="{bar_width}" height="{final_h}" '
        f'fill="{final_color}" rx="2" />\n'
        f'<text x="{x_final + bar_width // 2}" y="{y_bottom - final_h - 5}" '
        f'text-anchor="middle" fill="{final_color}" font-size="10" font-weight="bold">{trust.score}</text>\n'
        f'<text x="{x_final + bar_width // 2}" y="{y_bottom + 15}" '
        f'text-anchor="middle" fill="#aaa" font-size="9">Final</text>\n'
    )

    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">\n'
        f'{bars_svg}'
        f'</svg>'
    )


def generate_html_report(
    model_name: str,
    trust: TrustScore,
    module_results: list[ModuleResult],
    profile: str = "raw",
) -> str:
    """Generate a self-contained HTML report.

    Returns a complete HTML string with inline CSS/JS.
    """
    # Module pass rates for radar chart
    pass_rates = {}
    for r in module_results:
        if r.module_name != "CONTAMINATION_CHECK":
            pass_rates[r.module_name] = r.pass_rate

    radar_svg = _generate_radar_svg(pass_rates)
    waterfall_svg = _generate_waterfall_svg(trust)

    # Score color
    if trust.score >= 90:
        score_color = "#10b981"  # Bright green
    elif trust.score >= 75:
        score_color = "#34d399"  # Lighter green
    elif trust.score >= 60:
        score_color = "#f59e0b"
    elif trust.score >= 40:
        score_color = "#ef4444"
    else:
        score_color = "#ef4444"

    # Build findings HTML
    findings_html = ""
    for f in trust.findings:
        if f.level == "CRITICAL":
            badge = '<span class="badge critical">CRITICAL</span>'
        elif f.level == "WARNING":
            badge = '<span class="badge warning">WARNING</span>'
        else:
            badge = '<span class="badge clean">CLEAN</span>'

        detail = ""
        if f.probe_id:
            detail = f'<div class="finding-detail">Probe: {html.escape(f.probe_id)} | Module: {html.escape(f.module_name)} | Deduction: -{f.deduction:.1f}</div>'

        findings_html += f'<div class="finding">{badge} {html.escape(f.summary)}{detail}</div>\n'

    # Build probe accordion
    accordion_html = ""
    for mr in module_results:
        if mr.module_name == "CONTAMINATION_CHECK":
            continue
        label = MODULE_LABELS.get(mr.module_name, mr.module_name)
        probes_html = ""
        for pr in mr.probe_results:
            status = "pass" if pr.passed else "fail"
            icon = "PASS" if pr.passed else "FAIL"
            probes_html += (
                f'<div class="probe {status}">'
                f'<span class="probe-icon">{icon}</span> '
                f'<strong>{html.escape(pr.probe_name)}</strong> '
                f'<span class="probe-score">({pr.score:.1f})</span><br>'
                f'<span class="probe-reason">{html.escape(pr.reason)}</span>'
                f'</div>\n'
            )
        accordion_html += (
            f'<details class="module-section">'
            f'<summary>{html.escape(label)} -- {mr.passed_probes}/{mr.total_probes} passed</summary>'
            f'<div class="probes">{probes_html}</div>'
            f'</details>\n'
        )

    seed_line = f'<p class="meta">Seed: {trust.seed}</p>' if trust.seed is not None else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gauntlet Report -- {html.escape(model_name)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #0a0a0f; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace; padding: 2rem; max-width: 900px; margin: 0 auto; }}
  h1 {{ color: #00d4ff; font-size: 1.5rem; margin-bottom: 0.5rem; }}
  h2 {{ color: #7c3aed; font-size: 1.1rem; margin: 2rem 0 1rem; border-bottom: 1px solid #333; padding-bottom: 0.5rem; }}
  .header {{ text-align: center; margin-bottom: 2rem; }}
  .score {{ font-size: 3rem; font-weight: bold; color: {score_color}; }}
  .score-label {{ color: #888; font-size: 0.9rem; }}
  .meta {{ color: #666; font-size: 0.8rem; margin: 0.25rem 0; }}
  .charts {{ display: flex; gap: 2rem; justify-content: center; flex-wrap: wrap; margin: 2rem 0; }}
  .chart {{ background: #1a1a2e; border-radius: 8px; padding: 1rem; }}
  .chart-title {{ color: #888; font-size: 0.8rem; text-align: center; margin-bottom: 0.5rem; }}
  .finding {{ padding: 0.5rem 0; border-bottom: 1px solid #222; }}
  .finding-detail {{ color: #666; font-size: 0.75rem; margin-top: 0.25rem; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; margin-right: 0.5rem; }}
  .badge.critical {{ background: #7f1d1d; color: #fca5a5; }}
  .badge.warning {{ background: #78350f; color: #fde68a; }}
  .badge.clean {{ background: #064e3b; color: #6ee7b7; }}
  details {{ margin: 0.5rem 0; }}
  summary {{ cursor: pointer; padding: 0.5rem; background: #1a1a2e; border-radius: 4px; color: #00d4ff; }}
  summary:hover {{ background: #252540; }}
  .probes {{ padding: 0.5rem 1rem; }}
  .probe {{ padding: 0.4rem 0; border-bottom: 1px solid #1a1a2e; }}
  .probe.fail {{ border-left: 3px solid #ef4444; padding-left: 0.5rem; }}
  .probe.pass {{ border-left: 3px solid #10b981; padding-left: 0.5rem; }}
  .probe-icon {{ font-weight: bold; font-size: 0.75rem; }}
  .probe.pass .probe-icon {{ color: #10b981; }}
  .probe.fail .probe-icon {{ color: #ef4444; }}
  .probe-score {{ color: #888; font-size: 0.8rem; }}
  .probe-reason {{ color: #999; font-size: 0.8rem; }}
  .footer {{ text-align: center; color: #444; font-size: 0.7rem; margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #222; }}
  .warning-banner {{ background: #78350f; border: 1px solid #f59e0b; border-radius: 6px; padding: 1rem; margin: 1rem 0; text-align: center; }}
  .critical-banner {{ background: #7f1d1d; border: 1px solid #ef4444; border-radius: 6px; padding: 1rem; margin: 1rem 0; text-align: center; }}
</style>
</head>
<body>
<div class="header">
  <h1>GAUNTLET REPORT</h1>
  <p class="meta">{html.escape(model_name)} | Profile: {html.escape(profile)}</p>
  <div class="score">{trust.score}/100</div>
  <div class="score-label">Behavioral Trust Score</div>
  {seed_line}
</div>

{"<div class='critical-banner'><strong>CRITICAL SAFETY FAILURE</strong><br>This model complied with harmful requests.</div>" if trust.has_critical_safety else ""}
{"<div class='warning-banner'><strong>CONTAMINATION WARNING</strong><br>This model may have been trained on Gauntlet test data.</div>" if trust.contamination_warning else ""}

<div class="charts">
  <div class="chart">
    <div class="chart-title">Trust Dimensions</div>
    {radar_svg}
  </div>
  <div class="chart">
    <div class="chart-title">Deduction Waterfall</div>
    {waterfall_svg}
  </div>
</div>

<h2>Behavioral Findings</h2>
{findings_html}

<h2>Probe Details</h2>
{accordion_html}

<div class="footer">
  Generated by Gauntlet -- Behavioral reliability under pressure<br>
  <a href="https://basaltlabs.app" style="color:#7d93ab">Basalt Labs</a> | <a href="https://github.com/Basaltlabs-app/Gauntlet" style="color:#7d93ab">GitHub</a>
</div>
</body>
</html>"""
