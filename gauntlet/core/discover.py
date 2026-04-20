"""Model discovery -- list all available models across providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from gauntlet.core.config import get_api_key, PROVIDER_OPENAI, PROVIDER_ANTHROPIC, PROVIDER_GOOGLE
from gauntlet.core.providers.ollama import OllamaProvider
from gauntlet.core.providers.openai_provider import OpenAIProvider
from gauntlet.core.providers.anthropic_provider import AnthropicProvider
from gauntlet.core.providers.google_provider import GoogleProvider
from gauntlet.core.providers.lmstudio import LMStudioProvider


def get_system_memory() -> dict:
    """Get system memory info in GB."""
    import psutil
    mem = psutil.virtual_memory()
    return {
        "total_gb": round(mem.total / (1024**3), 1),
        "available_gb": round(mem.available / (1024**3), 1),
        "used_gb": round(mem.used / (1024**3), 1),
        "percent": mem.percent,
    }


def get_max_model_size_gb() -> float:
    """Get the max model size that can safely run on this machine.

    Rule of thumb: model should use at most 70% of available RAM
    to leave room for OS, Ollama overhead, and the app itself.
    """
    mem = get_system_memory()
    return round(mem["available_gb"] * 0.70, 1)


@dataclass
class DiscoveredModel:
    """A model discovered from a provider."""

    name: str
    provider: str
    size: Optional[int] = None
    parameter_size: Optional[str] = None
    quantization: Optional[str] = None
    family: Optional[str] = None
    multimodal: bool = False
    display_name: Optional[str] = None

    @property
    def size_gb(self) -> Optional[float]:
        if self.size:
            return round(self.size / (1024**3), 1)
        return None

    @property
    def fits_in_memory(self) -> bool:
        """Check if this model can run without swapping."""
        if self.size_gb is None:
            return True  # cloud models, no size info
        max_size = get_max_model_size_gb()
        return self.size_gb <= max_size

    @property
    def memory_warning(self) -> Optional[str]:
        """Return a warning if the model is too large for this machine."""
        if self.size_gb is None:
            return None
        mem = get_system_memory()
        if self.size_gb > mem["available_gb"]:
            return f"Model is {self.size_gb}GB but only {mem['available_gb']}GB available. Will be extremely slow."
        if self.size_gb > mem["available_gb"] * 0.7:
            return f"Model is {self.size_gb}GB which is tight for {mem['total_gb']}GB RAM. May be slow."
        return None

    @property
    def spec(self) -> str:
        """Return the full model specifier for use with gauntlet."""
        if self.provider == "ollama":
            return self.name
        return f"{self.provider}:{self.name}"

    @property
    def is_local(self) -> bool:
        """Whether this model runs on local hardware (not a cloud API)."""
        return self.provider in ("ollama", "lmstudio", "llamacpp")


async def discover_ollama() -> list[DiscoveredModel]:
    """Discover models from local Ollama installation."""
    ollama = OllamaProvider()
    if not await ollama.check_connection():
        return []

    raw_models = await ollama.list_models()
    models = []
    for m in raw_models:
        families = m.get("families") or []
        multimodal = any(f in families for f in ["clip", "mllama"])
        models.append(
            DiscoveredModel(
                name=m["name"],
                provider="ollama",
                size=m.get("size"),
                parameter_size=m.get("parameter_size"),
                quantization=m.get("quantization"),
                family=m.get("family"),
                multimodal=multimodal,
            )
        )
    return models


async def discover_lmstudio() -> list[DiscoveredModel]:
    """Discover currently-loaded models from LM Studio's local server.

    Returns an empty list if LM Studio isn't running or the server is off.
    The list reflects only the models the user has loaded in LM Studio,
    not every model on disk — loaded models are the ones runnable.
    """
    lmstudio = LMStudioProvider()
    if not await lmstudio.check_connection():
        return []

    raw_models = await lmstudio.list_models()
    models = []
    for m in raw_models:
        models.append(
            DiscoveredModel(
                name=m["name"],
                provider="lmstudio",
                display_name=m["name"],
            )
        )
    return models


async def discover_openai() -> list[DiscoveredModel]:
    """Discover models from OpenAI (if API key is set)."""
    api_key = get_api_key(PROVIDER_OPENAI)
    if not api_key:
        return []

    provider = OpenAIProvider(api_key=api_key)
    raw_models = await provider.list_models()
    return [
        DiscoveredModel(
            name=m["name"],
            provider="openai",
            display_name=m["name"],
        )
        for m in raw_models
        if any(
            prefix in m["name"]
            for prefix in ("gpt-", "o1", "o3", "o4", "chatgpt")
        )
    ]


async def discover_anthropic() -> list[DiscoveredModel]:
    """Discover models from Anthropic (if API key is set)."""
    api_key = get_api_key(PROVIDER_ANTHROPIC)
    if not api_key:
        return []

    provider = AnthropicProvider(api_key=api_key)
    raw_models = await provider.list_models()
    return [
        DiscoveredModel(
            name=m["name"],
            provider="anthropic",
            display_name=m["name"],
            multimodal=True,
        )
        for m in raw_models
    ]


async def discover_google() -> list[DiscoveredModel]:
    """Discover models from Google (if API key is set)."""
    api_key = get_api_key(PROVIDER_GOOGLE)
    if not api_key:
        return []

    provider = GoogleProvider(api_key=api_key)
    raw_models = await provider.list_models()
    return [
        DiscoveredModel(
            name=m["name"],
            provider="google",
            display_name=m.get("display_name", m["name"]),
        )
        for m in raw_models
    ]


async def discover_all() -> list[DiscoveredModel]:
    """Discover all available models across all providers."""
    import asyncio

    results = await asyncio.gather(
        discover_ollama(),
        discover_lmstudio(),
        discover_openai(),
        discover_anthropic(),
        discover_google(),
        return_exceptions=True,
    )

    all_models = []
    for result in results:
        if isinstance(result, list):
            all_models.extend(result)
    return all_models
