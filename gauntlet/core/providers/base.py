"""Base provider interface for all LLM backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""

    text: str
    done: bool = False
    # Provider-specific metadata (eval_count, eval_duration, etc.)
    meta: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    """Complete result from a model generation."""

    model: str
    provider: str
    output: str
    total_tokens: int
    eval_duration_ns: Optional[int] = None  # nanoseconds
    total_duration_ns: Optional[int] = None
    prompt_tokens: Optional[int] = None
    # Raw provider response metadata
    raw_meta: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    provider_name: str = "base"

    @abstractmethod
    async def stream_generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream tokens from the model. Yields StreamChunk objects."""
        ...

    @abstractmethod
    async def list_models(self) -> list[dict]:
        """List available models for this provider.

        Returns a list of dicts with at least {"name": str, "size": int|None}.
        """
        ...

    @abstractmethod
    async def check_connection(self) -> bool:
        """Check if the provider is reachable and configured."""
        ...
