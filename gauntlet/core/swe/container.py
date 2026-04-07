"""Docker container management for safe code execution."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ContainerResult:
    """Result from running tests in a Docker container."""
    exit_code: int
    stdout: str
    stderr: str
    tests_passed: int
    tests_failed: int
    tests_total: int
    duration_s: float

    @property
    def all_passed(self) -> bool:
        return self.tests_failed == 0 and self.tests_passed > 0


def check_docker() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def build_test_image(test_pack_dir: Path, tag: str = "gauntlet-test") -> bool:
    """Build a Docker image for a test pack.

    The test pack directory must contain a Dockerfile.
    """
    dockerfile = test_pack_dir / "Dockerfile"
    if not dockerfile.exists():
        # Generate a default Python Dockerfile
        dockerfile.write_text(
            "FROM python:3.11-slim\n"
            "WORKDIR /workspace\n"
            "COPY requirements.txt* ./\n"
            "RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true\n"
            "RUN pip install --no-cache-dir pytest\n"
            "COPY . .\n"
        )

    result = subprocess.run(
        ["docker", "build", "-t", tag, "."],
        cwd=str(test_pack_dir),
        capture_output=True, text=True, timeout=120,
    )
    return result.returncode == 0


def run_in_container(
    image: str,
    fix_code: str,
    test_code: str,
    test_command: str = "python -m pytest /workspace/test_fix.py -v --tb=short",
    timeout: int = 60,
) -> ContainerResult:
    """Run a model's fix inside a Docker container against a test suite.

    1. Writes the model's fix to a temp dir as fix.py
    2. Writes the test suite as test_fix.py
    3. Mounts both into the container
    4. Runs pytest
    5. Returns results

    Network is disabled. Memory limited to 512MB. CPU limited to 1 core.
    """
    import time

    tmpdir = tempfile.mkdtemp(prefix="gauntlet-swe-")
    fix_path = Path(tmpdir) / "fix.py"
    test_path = Path(tmpdir) / "test_fix.py"

    fix_path.write_text(fix_code)
    test_path.write_text(test_code)

    start = time.perf_counter()

    try:
        cmd = [
            "docker", "run", "--rm",
            "--network=none",
            "--memory=512m",
            "--cpus=1",
            "-v", f"{tmpdir}:/workspace",
            image,
            "sh", "-c", test_command,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )

        elapsed = time.perf_counter() - start
        stdout = result.stdout
        stderr = result.stderr

        passed, failed, total = _parse_pytest_output(stdout + stderr)

        return ContainerResult(
            exit_code=result.returncode,
            stdout=stdout[-2000:],
            stderr=stderr[-1000:],
            tests_passed=passed,
            tests_failed=failed,
            tests_total=total,
            duration_s=elapsed,
        )

    except subprocess.TimeoutExpired:
        return ContainerResult(
            exit_code=-1, stdout="", stderr="Timeout",
            tests_passed=0, tests_failed=0, tests_total=0,
            duration_s=time.perf_counter() - start,
        )
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _parse_pytest_output(output: str) -> tuple[int, int, int]:
    """Parse pytest output to extract pass/fail counts."""
    import re

    # Look for "X passed, Y failed" pattern
    passed = 0
    failed = 0

    # pytest summary line: "5 passed, 2 failed in 1.23s"
    match = re.search(r"(\d+) passed", output)
    if match:
        passed = int(match.group(1))

    match = re.search(r"(\d+) failed", output)
    if match:
        failed = int(match.group(1))

    match = re.search(r"(\d+) error", output)
    if match:
        failed += int(match.group(1))

    total = passed + failed
    return passed, failed, total
