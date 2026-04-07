"""Google Gemini provider via the Generative Language API."""

from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from gauntlet.core.providers.base import LLMProvider, StreamChunk


class GoogleProvider(LLMProvider):
    """Provider for Google Gemini models."""

    provider_name = "google"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def stream_generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream tokens from the Google Gemini API."""
        contents = []

        if image_path:
            import base64
            from pathlib import Path

            img_data = base64.b64encode(Path(image_path).read_bytes()).decode()
            contents.append(
                {
                    "parts": [
                        {"inline_data": {"mime_type": "image/jpeg", "data": img_data}},
                        {"text": prompt},
                    ]
                }
            )
        else:
            contents.append({"parts": [{"text": prompt}]})

        payload: dict = {"contents": contents}
        if system:
            payload["system_instruction"] = {"parts": [{"text": system}]}

        url = (
            f"{self.base_url}/models/{model}:streamGenerateContent"
            f"?key={self.api_key}&alt=sse"
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue

                    candidate = candidates[0]
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])
                    text = "".join(p.get("text", "") for p in parts)

                    finish_reason = candidate.get("finishReason")
                    done = finish_reason is not None and finish_reason != "STOP"

                    chunk = StreamChunk(text=text, done=False)

                    if finish_reason == "STOP":
                        usage = data.get("usageMetadata", {})
                        chunk.done = True
                        chunk.meta = {
                            "prompt_tokens": usage.get("promptTokenCount"),
                            "output_tokens": usage.get("candidatesTokenCount"),
                            "total_tokens": usage.get("totalTokenCount"),
                            "finish_reason": finish_reason,
                        }

                    yield chunk

    async def list_models(self) -> list[dict]:
        """List available Gemini models."""
        try:
            url = f"{self.base_url}/models?key={self.api_key}"
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            return [
                {
                    "name": m["name"].replace("models/", ""),
                    "size": None,
                    "display_name": m.get("displayName"),
                }
                for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
        except (httpx.HTTPError, KeyError):
            return []

    async def check_connection(self) -> bool:
        """Check if the Google API key is configured and valid."""
        if not self.api_key:
            return False
        try:
            url = f"{self.base_url}/models?key={self.api_key}"
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
