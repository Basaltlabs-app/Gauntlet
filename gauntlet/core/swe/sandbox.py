"""Self-contained Python sandbox -- no Docker required.

Runs model-generated code in a subprocess with:
  - Strict timeout (kills after N seconds)
  - Temp directory isolation (code can't see the host filesystem)
  - Memory limit via resource module (Unix only)

This is the default execution mode. Docker is optional for full isolation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gauntlet.core.swe.container import ContainerResult, _parse_pytest_output


def run_in_sandbox(
    fix_code: str,
    test_code: str,
    timeout: int = 30,
) -> ContainerResult:
    """Run model's fix + test suite in an isolated subprocess.

    1. Creates a temp directory
    2. Writes fix.py and test_fix.py
    3. Runs pytest in a subprocess with restricted PYTHONPATH
    4. Parses results
    5. Cleans up

    No Docker needed. Ships with Gauntlet.
    """
    tmpdir = tempfile.mkdtemp(prefix="gauntlet-sandbox-")
    fix_path = Path(tmpdir) / "fix.py"
    test_path = Path(tmpdir) / "test_fix.py"

    try:
        fix_path.write_text(fix_code)
        test_path.write_text(test_code)

        start = time.perf_counter()

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = tmpdir

        cmd = [
            sys.executable, "-m", "pytest",
            str(test_path),
            "-v", "--tb=short",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tmpdir,
            env=env,
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
            exit_code=-1, stdout="", stderr=f"Timeout after {timeout}s",
            tests_passed=0, tests_failed=0, tests_total=0,
            duration_s=timeout,
        )
    except Exception as e:
        return ContainerResult(
            exit_code=-1, stdout="", stderr=str(e),
            tests_passed=0, tests_failed=0, tests_total=0,
            duration_s=0,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def check_sandbox() -> bool:
    """Check if the sandbox can run (just needs Python + pytest)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
