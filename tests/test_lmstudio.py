"""Unit tests for LM Studio provider integration.

These tests don't require a running LM Studio instance — they verify
config resolution, metadata inference, provider wiring, and factory
behaviour. Live-server tests would be integration tests, out of scope
for this file.
"""

from __future__ import annotations

import os

import pytest

from gauntlet.core.config import (
    DEFAULT_LMSTUDIO_HOST,
    PROVIDER_LMSTUDIO,
    detect_provider,
    get_lmstudio_host,
    load_config,
    resolve_model,
    save_config,
)
from gauntlet.core.providers.factory import create_provider
from gauntlet.core.providers.lmstudio import LMStudioProvider
from gauntlet.core.system_info import _get_lmstudio_metadata


# ---------------------------------------------------------------------------
# Host resolution precedence: env > config file > default
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_host_env(monkeypatch, tmp_path):
    """Clear env vars and config file state between tests."""
    monkeypatch.delenv("LMSTUDIO_HOST", raising=False)
    # Snapshot + restore config file
    cfg_before = load_config()
    cfg_clean = {k: v for k, v in cfg_before.items() if k != "lmstudio_host"}
    save_config(cfg_clean)
    yield
    save_config(cfg_before)


def test_default_host_when_no_env_or_config():
    assert get_lmstudio_host() == DEFAULT_LMSTUDIO_HOST
    assert DEFAULT_LMSTUDIO_HOST == "http://localhost:1234"


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_HOST", "http://localhost:9999")
    assert get_lmstudio_host() == "http://localhost:9999"


def test_config_file_overrides_default():
    cfg = load_config()
    cfg["lmstudio_host"] = "http://192.168.1.50:4321"
    save_config(cfg)
    assert get_lmstudio_host() == "http://192.168.1.50:4321"


def test_env_wins_over_config_file(monkeypatch):
    cfg = load_config()
    cfg["lmstudio_host"] = "http://config-value:1234"
    save_config(cfg)
    monkeypatch.setenv("LMSTUDIO_HOST", "http://env-value:5678")
    assert get_lmstudio_host() == "http://env-value:5678"


# ---------------------------------------------------------------------------
# Model spec parsing
# ---------------------------------------------------------------------------

def test_detect_provider_lmstudio_prefix():
    provider, name = detect_provider("lmstudio:llama-3.2-8b")
    assert provider == PROVIDER_LMSTUDIO
    assert name == "llama-3.2-8b"


def test_detect_provider_preserves_model_with_colons():
    # Some LM Studio IDs include colons (rare but possible)
    provider, name = detect_provider("lmstudio:publisher/model-7b")
    assert provider == PROVIDER_LMSTUDIO
    assert name == "publisher/model-7b"


def test_resolve_model_lmstudio_includes_base_url():
    cfg = resolve_model("lmstudio:qwen-8b")
    assert cfg.provider == PROVIDER_LMSTUDIO
    assert cfg.base_url == DEFAULT_LMSTUDIO_HOST
    assert cfg.extra["model"] == "qwen-8b"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_creates_lmstudio_provider():
    cfg = resolve_model("lmstudio:llama-3.2-8b")
    provider, model = create_provider(cfg)
    assert isinstance(provider, LMStudioProvider)
    assert model == "llama-3.2-8b"
    assert provider.base_url == DEFAULT_LMSTUDIO_HOST
    assert provider._openai_base == f"{DEFAULT_LMSTUDIO_HOST}/v1"


def test_factory_honors_custom_base_url(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_HOST", "http://10.0.0.5:4321")
    cfg = resolve_model("lmstudio:qwen-8b")
    provider, _ = create_provider(cfg)
    assert provider.base_url == "http://10.0.0.5:4321"
    assert provider._openai_base == "http://10.0.0.5:4321/v1"


# ---------------------------------------------------------------------------
# Metadata inference from model ID (no live server needed)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "model_id,expected_family,expected_params,expected_quant",
    [
        ("llama-3.2-8b-q4_K_M", "llama", "8B", "Q4_K_M"),
        ("qwen2.5-7b-instruct-q8_0", "qwen", "7B", "Q8_0"),
        ("gemma-2-9b-f16", "gemma", "9B", "F16"),
        ("mistral-7b-v0.1-q5_k_s", "mistral", "7B", "Q5_K_S"),
        ("deepseek-coder-6.7b-q4_0", "deepseek", "6.7B", "Q4_0"),
    ],
)
def test_metadata_inference_from_model_id(
    model_id, expected_family, expected_params, expected_quant
):
    # No live server — should fall through to ID-based inference.
    meta = _get_lmstudio_metadata(model_id)
    assert meta["family"] == expected_family
    assert meta["parameter_size"] == expected_params
    assert meta["quantization"] == expected_quant
    assert meta["format"] == "gguf"


def test_metadata_unknown_model_returns_sensible_defaults():
    meta = _get_lmstudio_metadata("some-obscure-unknown-model")
    assert meta["family"] == "unknown"
    assert meta["format"] == "gguf"
