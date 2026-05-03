"""Tests for gauntlet._bootstrap_env — the .env loader that runs at
package import so MCP-spawned subprocesses (Gemini CLI, Claude Desktop,
Cursor) see Supabase creds without inheriting the parent shell.

The function is left importable on the module (not `del`-ed) specifically
so we can re-invoke it from tests without touching sys.modules.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import gauntlet


# Match the allowlist in gauntlet/__init__.py — sentinel values used in tests
# must be in this set, otherwise the loader will skip them on purpose.
ALLOWED_KEYS = {
    "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_ANON_KEY",
    "GAUNTLET_SUBMIT_KEY", "GAUNTLET_ALLOW_LOCAL",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    "OLLAMA_HOST", "LMSTUDIO_HOST",
}


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every key the loader might touch, plus the explicit override."""
    for key in ALLOWED_KEYS | {"GAUNTLET_ENV_FILE"}:
        monkeypatch.delenv(key, raising=False)


def test_bootstrap_loads_from_explicit_env_file(tmp_path, clean_env, monkeypatch):
    env_file = tmp_path / "creds.env"
    env_file.write_text(
        "SUPABASE_URL=https://test.supabase.co\n"
        "SUPABASE_SERVICE_KEY=test-key-xyz\n"
    )
    monkeypatch.setenv("GAUNTLET_ENV_FILE", str(env_file))
    monkeypatch.chdir(tmp_path)

    gauntlet._bootstrap_env()

    assert os.environ["SUPABASE_URL"] == "https://test.supabase.co"
    assert os.environ["SUPABASE_SERVICE_KEY"] == "test-key-xyz"


def test_bootstrap_never_overwrites_existing_env(tmp_path, clean_env, monkeypatch):
    """Parent process env always wins. Safety invariant — a stale .env file
    must never clobber what the user explicitly set."""
    env_file = tmp_path / ".env"
    env_file.write_text("SUPABASE_URL=from-file\n")
    monkeypatch.setenv("GAUNTLET_ENV_FILE", str(env_file))
    monkeypatch.setenv("SUPABASE_URL", "from-shell")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "shell-key")  # short-circuit guard
    monkeypatch.chdir(tmp_path)

    gauntlet._bootstrap_env()

    assert os.environ["SUPABASE_URL"] == "from-shell"


def test_bootstrap_finds_env_in_cwd(tmp_path, clean_env, monkeypatch):
    """`.env` in the current directory should be picked up automatically."""
    (tmp_path / ".env").write_text(
        "SUPABASE_URL=https://cwd.supabase.co\n"
        "SUPABASE_SERVICE_KEY=cwd-key\n"
    )
    monkeypatch.chdir(tmp_path)

    gauntlet._bootstrap_env()

    assert os.environ["SUPABASE_URL"] == "https://cwd.supabase.co"


def test_bootstrap_walks_up_to_repo_root(tmp_path, clean_env, monkeypatch):
    """If cwd has no .env but an ancestor (with pyproject.toml) does, find it."""
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("")  # marks repo root
    (repo / ".env.vercel.local").write_text(
        "SUPABASE_URL=ancestor-url\nSUPABASE_SERVICE_KEY=k\n"
    )
    sub = repo / "sub" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)

    gauntlet._bootstrap_env()

    assert os.environ["SUPABASE_URL"] == "ancestor-url"


def test_bootstrap_only_loads_allowlisted_keys(tmp_path, clean_env, monkeypatch):
    """Loader must NOT dump arbitrary keys from .env — that'd surprise users
    who put unrelated secrets in their .env."""
    (tmp_path / ".env").write_text(
        "SUPABASE_URL=allowed\n"
        "SUPABASE_SERVICE_KEY=allowed-too\n"
        "MY_PRIVATE_KEY=should-not-leak\n"
        "ARBITRARY_CONFIG=should-not-leak\n"
    )
    monkeypatch.chdir(tmp_path)

    gauntlet._bootstrap_env()

    assert os.environ.get("SUPABASE_URL") == "allowed"
    assert "MY_PRIVATE_KEY" not in os.environ
    assert "ARBITRARY_CONFIG" not in os.environ


def test_bootstrap_strips_quotes_and_export_prefix(tmp_path, clean_env, monkeypatch):
    (tmp_path / ".env").write_text(
        'export SUPABASE_URL="https://quoted.supabase.co"\n'
        "SUPABASE_SERVICE_KEY='single-quoted'\n"
    )
    monkeypatch.chdir(tmp_path)

    gauntlet._bootstrap_env()

    assert os.environ["SUPABASE_URL"] == "https://quoted.supabase.co"
    assert os.environ["SUPABASE_SERVICE_KEY"] == "single-quoted"


def test_bootstrap_skips_comments_and_blank_lines(tmp_path, clean_env, monkeypatch):
    (tmp_path / ".env").write_text(
        "# this is a comment\n"
        "\n"
        "SUPABASE_URL=ok\n"
        "# SUPABASE_SERVICE_KEY=commented-out\n"
        "SUPABASE_SERVICE_KEY=real-key\n"
    )
    monkeypatch.chdir(tmp_path)

    gauntlet._bootstrap_env()

    assert os.environ["SUPABASE_URL"] == "ok"
    assert os.environ["SUPABASE_SERVICE_KEY"] == "real-key"


def test_bootstrap_silent_on_missing_file(tmp_path, clean_env, monkeypatch):
    """No .env anywhere = no error, gauntlet still imports cleanly."""
    monkeypatch.setenv("GAUNTLET_ENV_FILE", "/nonexistent/path/.env")
    monkeypatch.chdir(tmp_path)
    # Should not raise
    gauntlet._bootstrap_env()
    # And no Supabase vars should be set
    assert os.environ.get("SUPABASE_URL", "") == ""


def test_bootstrap_is_idempotent(tmp_path, clean_env, monkeypatch):
    """Calling _bootstrap_env twice should be a no-op the second time."""
    (tmp_path / ".env").write_text(
        "SUPABASE_URL=first-load\nSUPABASE_SERVICE_KEY=first-key\n"
    )
    monkeypatch.chdir(tmp_path)

    gauntlet._bootstrap_env()
    assert os.environ["SUPABASE_URL"] == "first-load"

    # Even if we update the file, the second call should not overwrite the
    # already-set env (because the user might have manually exported it).
    (tmp_path / ".env").write_text(
        "SUPABASE_URL=second-load\nSUPABASE_SERVICE_KEY=second-key\n"
    )
    gauntlet._bootstrap_env()
    assert os.environ["SUPABASE_URL"] == "first-load"
