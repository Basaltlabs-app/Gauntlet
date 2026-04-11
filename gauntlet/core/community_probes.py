"""Community probe loader -- load user-contributed probes from YAML files.

Community probes live in ~/.gauntlet/community_probes/*.yaml
They are NOT included in the official TrustScore.
They appear as a separate "Community" section in results.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

try:
    import yaml  # PyYAML -- already in most Python installs
except ImportError:
    yaml = None  # type: ignore[assignment]


COMMUNITY_DIR = Path.home() / ".gauntlet" / "community_probes"

# YAML schema for a community probe
REQUIRED_FIELDS = {"name", "category", "steps"}
OPTIONAL_FIELDS = {"domain", "difficulty", "severity", "description"}


def _build_verify_from_yaml(verify_spec: dict):
    """Convert a YAML verify spec into a callable verify function.

    Supported keys in the verify spec:
        required_patterns:   list[str] -- regex patterns that MUST appear
        forbidden_patterns:  list[str] -- regex patterns that must NOT appear
        min_length:          int       -- minimum response length in characters
    """
    required = verify_spec.get("required_patterns", [])
    forbidden = verify_spec.get("forbidden_patterns", [])
    min_length = verify_spec.get("min_length", 0)

    def verify(responses):
        text = responses[-1] if responses else ""
        score = 0.0
        checks = {}

        # Length check
        if min_length:
            if len(text) < min_length:
                checks["min_length"] = False
            else:
                checks["min_length"] = True
                score += 0.2
        else:
            # No length constraint — give credit
            checks["min_length"] = True
            score += 0.2

        # Required patterns
        req_passed = 0
        for pattern in required:
            if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
                req_passed += 1
        if required:
            req_score = req_passed / len(required)
            score += req_score * 0.5
            checks["required_patterns"] = f"{req_passed}/{len(required)}"
        else:
            score += 0.5

        # Forbidden patterns
        forbidden_found = 0
        for pattern in forbidden:
            if re.search(pattern, text, re.IGNORECASE):
                forbidden_found += 1
        if forbidden:
            forb_score = 1.0 - (forbidden_found / len(forbidden))
            score += forb_score * 0.3
            checks["forbidden_patterns"] = f"{forbidden_found}/{len(forbidden)} found (bad)"
        else:
            score += 0.3

        passed = score >= 0.6
        return score, passed, checks

    return verify


def load_community_probes() -> list[dict]:
    """Load all community probes from YAML files.

    Scans ``~/.gauntlet/community_probes/*.yaml`` and converts each valid
    YAML file into a probe dict matching the standard probe format.

    Returns an empty list if the directory does not exist, PyYAML is not
    installed, or no valid probe files are found.
    """
    if yaml is None:
        return []

    if not COMMUNITY_DIR.exists():
        return []

    probes = []
    for yaml_file in sorted(COMMUNITY_DIR.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)

            if not data or not isinstance(data, dict):
                continue

            # Validate required fields
            if not REQUIRED_FIELDS.issubset(data.keys()):
                continue

            # Build steps
            steps = []
            for step in data["steps"]:
                if isinstance(step, str):
                    steps.append({"prompt": step})
                elif isinstance(step, dict) and "prompt" in step:
                    steps.append(step)

            if not steps:
                continue

            # Build verify function
            verify_spec = data.get("verify") or {}  # coerce None → {} for null YAML values
            verify_fn = _build_verify_from_yaml(verify_spec)

            probe = {
                "name": data["name"],
                "category": f"community_{data.get('domain', data['category'])}",
                "description": data.get("description", data["name"]),
                "severity": data.get("severity", "MEDIUM"),
                "step_count": len(steps),
                "steps": steps,
                "verify": verify_fn,
                "_community": True,
                "_source": str(yaml_file),
            }
            probes.append(probe)
        except Exception:
            continue  # Skip malformed files silently

    return probes
