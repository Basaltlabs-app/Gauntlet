"""Factory for creating provider instances from config."""

from __future__ import annotations

from gauntlet.core.config import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_OPENAI_COMPAT,
    ProviderConfig,
    resolve_model,
)
from gauntlet.core.providers.anthropic_provider import AnthropicProvider
from gauntlet.core.providers.base import LLMProvider
from gauntlet.core.providers.google_provider import GoogleProvider
from gauntlet.core.providers.ollama import OllamaProvider
from gauntlet.core.providers.openai_provider import OpenAIProvider


def create_provider(config: ProviderConfig) -> tuple[LLMProvider, str]:
    """Create a provider instance and return (provider, clean_model_name).

    Args:
        config: ProviderConfig from resolve_model()

    Returns:
        Tuple of (provider_instance, model_name_to_use)

    Raises:
        ValueError: If API key is required but missing
    """
    model = config.extra["model"]

    if config.provider == PROVIDER_OLLAMA:
        provider = OllamaProvider(base_url=config.base_url or "http://localhost:11434")
        return provider, model

    if config.provider == PROVIDER_OPENAI:
        if not config.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY environment variable."
            )
        provider = OpenAIProvider(api_key=config.api_key)
        return provider, model

    if config.provider == PROVIDER_OPENAI_COMPAT:
        if not config.api_key:
            raise ValueError(
                "API key required for OpenAI-compatible endpoint. Set OPENAI_API_KEY."
            )
        provider = OpenAIProvider(
            api_key=config.api_key, base_url=config.base_url or ""
        )
        return provider, model

    if config.provider == PROVIDER_ANTHROPIC:
        if not config.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable."
            )
        provider = AnthropicProvider(api_key=config.api_key)
        return provider, model

    if config.provider == PROVIDER_GOOGLE:
        if not config.api_key:
            raise ValueError(
                "Google API key required. Set GOOGLE_API_KEY environment variable."
            )
        provider = GoogleProvider(api_key=config.api_key)
        return provider, model

    raise ValueError(f"Unknown provider: {config.provider}")


def provider_from_spec(model_spec: str) -> tuple[LLMProvider, str]:
    """Convenience: resolve a model spec string directly to (provider, model_name)."""
    config = resolve_model(model_spec)
    return create_provider(config)
