"""Configuration and defaults for Gauntlet."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _resolve_gauntlet_dir() -> Path:
    """Resolve the data directory, falling back to /tmp on read-only filesystems."""
    home_dir = Path.home() / ".gauntlet"
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        return home_dir
    except OSError:
        # Vercel serverless: home is read-only, use /tmp
        tmp_dir = Path("/tmp/.gauntlet")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir


GAUNTLET_DIR = _resolve_gauntlet_dir()
LEADERBOARD_FILE = GAUNTLET_DIR / "leaderboard.json"
CONFIG_FILE = GAUNTLET_DIR / "config.json"

# Ollama defaults
DEFAULT_OLLAMA_HOST = "http://localhost:11434"

# Provider identifiers
PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GOOGLE = "google"
PROVIDER_OPENAI_COMPAT = "openai-compatible"
PROVIDER_LLAMACPP = "llamacpp"
PROVIDER_LMSTUDIO = "lmstudio"

# llama.cpp defaults
DEFAULT_LLAMACPP_HOST = "http://localhost:8080"

# LM Studio defaults (LM Studio's built-in local server)
DEFAULT_LMSTUDIO_HOST = "http://localhost:1234"


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    extra: dict = field(default_factory=dict)


def ensure_gauntlet_dir() -> Path:
    """Create ~/.gauntlet/ if it doesn't exist."""
    GAUNTLET_DIR.mkdir(parents=True, exist_ok=True)
    return GAUNTLET_DIR


def _host_from_config(env_var: str, config_key: str, default: str) -> str:
    """Resolve a host with precedence: env var > config file > default."""
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val
    try:
        cfg = load_config()
        if cfg.get(config_key):
            return cfg[config_key]
    except Exception:
        pass
    return default


def get_ollama_host() -> str:
    """Get the Ollama API host (env > config > default)."""
    return _host_from_config("OLLAMA_HOST", "ollama_host", DEFAULT_OLLAMA_HOST)


def get_llamacpp_host() -> str:
    """Get the llama.cpp server host (env > config > default)."""
    return _host_from_config("LLAMACPP_HOST", "llamacpp_host", DEFAULT_LLAMACPP_HOST)


def get_lmstudio_host() -> str:
    """Get the LM Studio local server host (env > config > default).

    LM Studio lets users change the server port inside the app. Set the
    LMSTUDIO_HOST environment variable (e.g. http://localhost:4321) or
    persist via `gauntlet config --lmstudio-host=http://localhost:4321`.
    """
    return _host_from_config("LMSTUDIO_HOST", "lmstudio_host", DEFAULT_LMSTUDIO_HOST)


def detect_provider(model_name: str) -> tuple[str, str]:
    """Detect the provider and clean model name from a model specifier.

    Formats:
        "gemma4"                     -> (ollama, gemma4)
        "ollama:gemma4"              -> (ollama, gemma4)
        "openai:gpt-4o"              -> (openai, gpt-4o)
        "anthropic:claude-sonnet-4-20250514" -> (anthropic, claude-sonnet-4-20250514)
        "google:gemini-2.0-flash"    -> (google, gemini-2.0-flash)
        "lmstudio:llama-3.2-8b"      -> (lmstudio, llama-3.2-8b)
        "llamacpp:model"             -> (llamacpp, model)
        "http://host:port/v1:model"  -> (openai-compatible, model) with base_url
    """
    if ":" in model_name:
        prefix, _, rest = model_name.partition(":")

        # Check for known providers
        if prefix in (PROVIDER_OLLAMA, PROVIDER_OPENAI, PROVIDER_ANTHROPIC, PROVIDER_GOOGLE, PROVIDER_LLAMACPP, PROVIDER_LMSTUDIO):
            return prefix, rest

        # Check for URL-based custom endpoint (openai-compatible)
        if prefix in ("http", "https"):
            # Format: http://host:port/v1:model_name
            # Find the last colon that separates URL from model
            full = model_name
            last_colon = full.rfind(":")
            # Walk backwards to find the actual model separator
            # URLs have colons in protocol and port, so we look for the pattern
            # where what's after the colon looks like a model name (no slashes)
            parts = full.rsplit(":", 1)
            if len(parts) == 2 and "/" not in parts[1]:
                base_url = parts[0]
                model = parts[1]
                return PROVIDER_OPENAI_COMPAT, f"{base_url}||{model}"

        # Ollama model with tag (e.g. "gemma4:latest" or "qwen2.5:7b")
        return PROVIDER_OLLAMA, model_name

    return PROVIDER_OLLAMA, model_name


def get_api_key(provider: str) -> Optional[str]:
    """Get API key for a provider from environment variables."""
    env_map = {
        PROVIDER_OPENAI: "OPENAI_API_KEY",
        PROVIDER_ANTHROPIC: "ANTHROPIC_API_KEY",
        PROVIDER_GOOGLE: "GOOGLE_API_KEY",
        PROVIDER_OPENAI_COMPAT: "OPENAI_API_KEY",
    }
    env_var = env_map.get(provider)
    if env_var:
        return os.environ.get(env_var)
    return None


def resolve_model(model_spec: str) -> ProviderConfig:
    """Resolve a model specifier into a full provider config.

    Returns a ProviderConfig with provider name, API key, base URL, and
    the clean model name stored in extra["model"].
    """
    provider, model_name = detect_provider(model_spec)

    base_url = None
    if provider == PROVIDER_OPENAI_COMPAT and "||" in model_name:
        base_url, model_name = model_name.split("||", 1)
    elif provider == PROVIDER_OLLAMA:
        base_url = get_ollama_host()
    elif provider == PROVIDER_LMSTUDIO:
        base_url = get_lmstudio_host()
    elif provider == PROVIDER_LLAMACPP:
        base_url = get_llamacpp_host()

    api_key = get_api_key(provider)

    return ProviderConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        extra={"model": model_name, "original_spec": model_spec},
    )


def load_config() -> dict:
    """Load user config from ~/.gauntlet/config.json."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    """Save user config to ~/.gauntlet/config.json."""
    ensure_gauntlet_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
