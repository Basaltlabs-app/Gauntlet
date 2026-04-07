"""Ollama provider - local model execution."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx

from gauntlet.core.providers.base import GenerationResult, LLMProvider, StreamChunk


class OllamaProvider(LLMProvider):
    """Provider for locally running Ollama models."""

    provider_name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    async def stream_generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream tokens from an Ollama model."""
        payload: dict = {"model": model, "prompt": prompt, "stream": True}

        if system:
            payload["system"] = system

        if image_path:
            img_data = Path(image_path).read_bytes()
            payload["images"] = [base64.b64encode(img_data).decode()]

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/generate", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    chunk = StreamChunk(
                        text=data.get("response", ""),
                        done=data.get("done", False),
                    )
                    if chunk.done:
                        chunk.meta = {
                            "total_duration": data.get("total_duration"),
                            "eval_count": data.get("eval_count"),
                            "eval_duration": data.get("eval_duration"),
                            "prompt_eval_count": data.get("prompt_eval_count"),
                            "prompt_eval_duration": data.get("prompt_eval_duration"),
                        }
                    yield chunk

    async def list_models(self) -> list[dict]:
        """List installed Ollama models."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            details = m.get("details", {})
            models.append(
                {
                    "name": m["name"],
                    "size": m.get("size"),
                    "parameter_size": details.get("parameter_size"),
                    "quantization": details.get("quantization_level"),
                    "family": details.get("family"),
                    "families": details.get("families"),
                    "format": details.get("format"),
                    "modified_at": m.get("modified_at"),
                }
            )
        return models

    async def get_model_info(self, model: str) -> dict:
        """Get detailed info for a specific model."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(
                f"{self.base_url}/api/show", json={"name": model}
            )
            resp.raise_for_status()
            return resp.json()

    async def check_connection(self) -> bool:
        """Check if Ollama is running."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
