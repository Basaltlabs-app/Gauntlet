"""Gauntlet - Behavioral reliability under pressure."""

from __future__ import annotations

__version__ = "2.1.2"

__all__ = ["__version__"]


def _bootstrap_env() -> None:
    """Load dotenv-style files so gauntlet works under MCP clients (Gemini CLI,
    Claude Desktop, etc.) that spawn a Python subprocess without inheriting the
    parent shell's exported env.

    Priority (first hit wins per key, existing env is **never** overwritten):
        1. Environment already set in the parent process (highest priority)
        2. $GAUNTLET_ENV_FILE pointing at a specific file, if set
        3. .env.vercel.local / .env.local / .env in CWD
        4. Same files, walking up ancestor dirs until a repo root (has .git or
           pyproject.toml) or filesystem root
        5. ~/.gauntlet/.env (global fallback, works when gauntlet is launched
           from anywhere — e.g. Gemini CLI / Claude Desktop spawned subprocess)

    Only specific keys are loaded — never a blanket dump — to avoid surprising
    users who have unrelated vars in their .env files. Extend KEYS_OF_INTEREST
    if gauntlet grows more env-var dependencies.

    Failures are silent; a missing .env is the expected happy path on Vercel
    (env is injected by the platform) and for users who export vars manually.
    """
    import os
    from pathlib import Path

    KEYS_OF_INTEREST = frozenset({
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "SUPABASE_ANON_KEY",
        "GAUNTLET_SUBMIT_KEY",
        "GAUNTLET_ALLOW_LOCAL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "OLLAMA_HOST",
        "LMSTUDIO_HOST",
    })

    # If every key we care about is already set, skip all I/O.
    if all(os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")):
        return

    candidates: list[Path] = []

    explicit = os.environ.get("GAUNTLET_ENV_FILE")
    if explicit:
        candidates.append(Path(explicit))

    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        candidates.extend([
            p / ".env.vercel.local",
            p / ".env.local",
            p / ".env",
        ])
        if (p / ".git").exists() or (p / "pyproject.toml").exists():
            # stop at repo root — don't walk into the user's $HOME
            break

    # Global fallback: ~/.gauntlet/.env (for gauntlet installed as a CLI and
    # invoked by MCP clients launched from anywhere — Gemini CLI, Dock apps).
    try:
        candidates.append(Path.home() / ".gauntlet" / ".env")
    except (OSError, RuntimeError):
        pass

    seen: set[Path] = set()
    for path in candidates:
        try:
            path = path.resolve()
        except OSError:
            continue
        if path in seen or not path.is_file():
            continue
        seen.add(path)

        try:
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                # Strip an optional leading `export `
                if line.startswith("export "):
                    line = line[len("export "):]
                key, _, value = line.partition("=")
                key = key.strip()
                if key not in KEYS_OF_INTEREST:
                    continue
                # Strip surrounding quotes and a trailing comment
                value = value.strip()
                if value and value[0] in ("'", '"') and value.endswith(value[0]):
                    value = value[1:-1]
                # Never overwrite something already set in the real env
                os.environ.setdefault(key, value)
        except OSError:
            # unreadable file → skip quietly
            continue


_bootstrap_env()
# NOTE: _bootstrap_env is intentionally kept on the module (not `del`-ed) so
# tests can re-invoke it without the brittle "delete-from-sys.modules" dance.
# It's idempotent — repeat calls only set vars that aren't already set.
