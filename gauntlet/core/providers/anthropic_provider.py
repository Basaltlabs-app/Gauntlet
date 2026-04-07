"""Anthropic provider - Claude models via the Anthropic API."""

from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx

from gauntlet.core.providers.base import LLMProvider, StreamChunk


class AnthropicProvider(LLMProvider):
    """Provider for Anthropic Claude models."""

    provider_name = "anthropic"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1"

    async def stream_generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream tokens from the Anthropic API."""
        messages = []

        if image_path:
            import base64
            from pathlib import Path

            img_data = base64.b64encode(Path(image_path).read_bytes()).decode()
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": prompt})

        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": 4096,
            "stream": True,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/messages",
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type", "")

                    if event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        text = delta.get("text", "")
                        yield StreamChunk(text=text, done=False)

                    elif event_type == "message_delta":
                        usage = data.get("usage", {})
                        yield StreamChunk(
                            text="",
                            done=True,
                            meta={
                                "output_tokens": usage.get("output_tokens"),
                                "stop_reason": data.get("delta", {}).get(
                                    "stop_reason"
                                ),
                            },
                        )

                    elif event_type == "message_start":
                        # Capture input token count
                        msg = data.get("message", {})
                        usage = msg.get("usage", {})
                        if usage.get("input_tokens"):
                            yield StreamChunk(
                                text="",
                                done=False,
                                meta={"input_tokens": usage["input_tokens"]},
                            )

    async def list_models(self) -> list[dict]:
        """List available Anthropic models."""
        # Anthropic doesn't have a list models endpoint, return known models
        return [
            {"name": "claude-sonnet-4-20250514", "size": None},
            {"name": "claude-haiku-4-20250414", "size": None},
            {"name": "claude-opus-4-20250514", "size": None},
        ]

    async def check_connection(self) -> bool:
        """Check if the Anthropic API key is configured."""
        return bool(self.api_key)
