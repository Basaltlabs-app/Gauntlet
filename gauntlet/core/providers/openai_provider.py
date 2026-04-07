"""OpenAI-compatible provider - works with OpenAI, Together, Groq, any OpenAI-compatible API."""

from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from gauntlet.core.providers.base import LLMProvider, StreamChunk


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI and any OpenAI-compatible API."""

    provider_name = "openai"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def stream_generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream tokens from an OpenAI-compatible API."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})

        if image_path:
            import base64
            from pathlib import Path

            img_data = base64.b64encode(Path(image_path).read_bytes()).decode()
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_data}"},
                        },
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": prompt})

        payload = {"model": model, "messages": messages, "stream": True}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        yield StreamChunk(text="", done=True)
                        return
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    text = delta.get("content", "")
                    finish = choices[0].get("finish_reason")
                    chunk = StreamChunk(text=text, done=finish is not None)
                    if finish:
                        chunk.meta = {
                            "usage": data.get("usage", {}),
                            "finish_reason": finish,
                        }
                    yield chunk

    async def list_models(self) -> list[dict]:
        """List available models from the API."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    f"{self.base_url}/models", headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
            return [
                {"name": m["id"], "size": None, "owned_by": m.get("owned_by")}
                for m in data.get("data", [])
            ]
        except (httpx.HTTPError, KeyError):
            return []

    async def check_connection(self) -> bool:
        """Check if the API is reachable and the key is valid."""
        if not self.api_key:
            return False
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    f"{self.base_url}/models", headers=headers
                )
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
