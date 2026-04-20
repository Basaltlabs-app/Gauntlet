"""LM Studio provider - local server with OpenAI-compatible /v1 API.

LM Studio (https://lmstudio.ai) runs GGUF models locally and exposes an
OpenAI-compatible server on localhost:1234 by default. This provider
reuses the OpenAI streaming protocol but defaults to LM Studio's host
and a dummy API key (LM Studio accepts any non-empty key).

Users can override the host with the LMSTUDIO_HOST environment variable
since LM Studio lets users change the port inside the app.
"""

from __future__ import annotations

from typing import AsyncIterator, Optional

import httpx

from gauntlet.core.config import get_lmstudio_host
from gauntlet.core.providers.base import LLMProvider, StreamChunk
from gauntlet.core.providers.openai_provider import OpenAIProvider


class LMStudioProvider(LLMProvider):
    """Provider for LM Studio's local OpenAI-compatible server."""

    provider_name = "lmstudio"

    def __init__(self, base_url: Optional[str] = None, api_key: str = "lm-studio"):
        self.base_url = (base_url or get_lmstudio_host()).rstrip("/")
        # LM Studio doesn't validate the key but requires the header to exist.
        self.api_key = api_key or "lm-studio"
        self._openai_base = f"{self.base_url}/v1"
        self._delegate = OpenAIProvider(api_key=self.api_key, base_url=self._openai_base)

    async def stream_generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        async for chunk in self._delegate.stream_generate(
            model=model, prompt=prompt, system=system, image_path=image_path
        ):
            yield chunk

    async def list_models(self) -> list[dict]:
        """List currently-loaded models in LM Studio.

        LM Studio's /v1/models returns only the models the user has loaded
        in the app (not every model on disk). That's the right set for
        benchmarking — models must be loaded to be runnable.
        """
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(f"{self._openai_base}/models")
                resp.raise_for_status()
                data = resp.json()
            return [
                {
                    "name": m["id"],
                    "size": None,
                    "owned_by": m.get("owned_by"),
                    "object": m.get("object"),
                }
                for m in data.get("data", [])
            ]
        except (httpx.HTTPError, KeyError):
            return []

    async def check_connection(self) -> bool:
        """Check if LM Studio's local server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self._openai_base}/models")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
