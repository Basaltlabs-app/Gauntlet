"""Persistent retry queue for failed community submissions.

When `submit_result()` fails (network blip, Supabase outage, transient 5xx),
the result vanishes today — the user has no way to recover it. This module
queues the payload to ~/.gauntlet/pending/ and replays it on the next CLI
invocation. Self-healing without user intervention.

Layout:
    ~/.gauntlet/pending/
        20260503-141522-abc123.json   ← single submission payload
        20260503-141601-def456.json
        ...

Each file contains exactly the JSON body that would have been POSTed to
/api/submit. Filename format: <UTC timestamp>-<random hex>.json so they
sort lexicographically by submission time.

Drained on:
  - `gauntlet doctor` (manual)
  - First CLI run of any benchmark command (best-effort, daemon thread)
  - `gauntlet retry` (planned)

Invariants:
  - Failures during enqueue are silent (we don't want to crash the user's
    CLI because their disk is full).
  - Failures during drain leave the file in place — it'll retry next time.
  - Successful drain deletes the file.
  - The queue has a soft cap (MAX_PENDING) to avoid unbounded growth on a
    permanently-down API; oldest files are deleted past the cap.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger("gauntlet.submit_queue")

MAX_PENDING = 200  # soft cap; older files are pruned past this


def _queue_dir() -> Path:
    """Return the pending queue dir, creating it if missing."""
    d = Path.home() / ".gauntlet" / "pending"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug("Could not create %s: %s", d, e)
    return d


def enqueue(payload: dict) -> Optional[Path]:
    """Persist a failed submission to disk for later retry.

    Returns the path of the queued file, or None if disk write failed.
    """
    try:
        d = _queue_dir()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        nonce = secrets.token_hex(3)
        path = d / f"{ts}-{nonce}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Queued failed submission to %s", path.name)
        _enforce_cap(d)
        return path
    except (OSError, TypeError, ValueError) as e:
        logger.debug("Failed to enqueue submission: %s", e)
        return None


def _enforce_cap(d: Path) -> None:
    """Delete oldest files if the queue grows past MAX_PENDING."""
    try:
        files = sorted(d.glob("*.json"))
        if len(files) <= MAX_PENDING:
            return
        for f in files[: len(files) - MAX_PENDING]:
            try:
                f.unlink()
            except OSError:
                pass
    except OSError:
        pass


def list_pending() -> list[Path]:
    """Return all queued payloads, oldest first."""
    try:
        return sorted(_queue_dir().glob("*.json"))
    except OSError:
        return []


def iter_pending() -> Iterator[tuple[Path, dict]]:
    """Yield (path, payload) for each queued submission, oldest first.

    Files that fail to load are silently skipped (and logged at DEBUG). A
    corrupt JSON file shouldn't block the rest of the queue from draining.
    """
    for path in list_pending():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            yield path, payload
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Skipping corrupt queue file %s: %s", path.name, e)


def drain(timeout: float = 8.0) -> dict:
    """Replay all queued submissions. Returns a summary dict.

    Each successful retry deletes the file. Failures leave it in place. We
    stop after the first network error to avoid hammering a downed API —
    the next run will pick up where we left off.

    Returns:
        {"replayed": int, "remaining": int, "stopped_early": bool}
    """
    from gauntlet.core.submit import submit_result

    replayed = 0
    stopped_early = False

    for path, payload in iter_pending():
        try:
            resp = submit_result(payload, timeout=timeout)
        except Exception as e:
            logger.debug("Drain interrupted by exception: %s", e)
            stopped_early = True
            break

        if resp is None:
            # network error — bail rather than burn through every file
            stopped_early = True
            break

        if resp.status_code == 200:
            try:
                path.unlink()
                replayed += 1
            except OSError as e:
                logger.debug("Could not unlink %s: %s", path, e)
        elif 400 <= resp.status_code < 500:
            # Permanent rejection (validation, version pin). The payload will
            # never be accepted as-is, so delete it rather than retry forever.
            logger.warning(
                "Dropping permanently-rejected submission %s (HTTP %d): %s",
                path.name,
                resp.status_code,
                (resp.text or "").strip()[:200],
            )
            try:
                path.unlink()
            except OSError:
                pass
        else:
            # 5xx — server-side, transient. Stop and retry next run.
            stopped_early = True
            break

    remaining = len(list_pending())
    return {
        "replayed": replayed,
        "remaining": remaining,
        "stopped_early": stopped_early,
    }


def drain_in_background(timeout: float = 8.0) -> None:
    """Fire-and-forget drain in a daemon thread. Never blocks the caller."""
    if not list_pending():
        return  # nothing to do

    import threading

    def _run() -> None:
        try:
            result = drain(timeout=timeout)
            if result["replayed"]:
                logger.info(
                    "Drained %d queued submission(s); %d remaining",
                    result["replayed"],
                    result["remaining"],
                )
        except Exception as e:
            logger.debug("Background drain failed: %s", e)

    threading.Thread(target=_run, daemon=True).start()
