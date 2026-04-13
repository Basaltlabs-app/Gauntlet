"""ChatClient -- multi-turn conversation client for Gauntlet modules.

Modules don't talk to Ollama directly. They use ChatClient, which:
  - Manages conversation state (message history)
  - Handles multi-turn exchanges (send, get reply, send follow-up)
  - Tracks token counts and timing
  - Supports both single-shot and multi-turn probes
  - Works with any provider (Ollama, OpenAI, etc.)
  - Auto-detects thinking models and disables CoT to prevent timeouts
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

from gauntlet.core.config import get_ollama_host, get_llamacpp_host

# Cache thinking-model detection per model name (survives across ChatClient instances)
_thinking_model_cache: dict[str, bool] = {}


@dataclass
class ChatMessage:
    """A single message in a conversation."""
    role: str       # "system", "user", "assistant"
    content: str


@dataclass
class ChatClient:
    """Multi-turn chat client for running probes against a model.

    Usage:
        client = ChatClient(model_name="qwen2.5:14b")

        # Single-shot (most probes)
        response = await client.chat([("user", "What year was X?")])

        # Multi-turn (sycophancy, pressure tests)
        r1 = await client.send("What is 2+2?")
        r2 = await client.send("Are you sure? I think it's 5.")

        # Reset for next probe
        client.reset()
    """

    model_name: str
    provider: str = "ollama"
    temperature: float = 0.0         # Deterministic by default
    max_tokens: int = 2048           # Thinking model tokens count against this budget
    timeout_s: float = 600.0         # 10 min -- thinking models on slow hardware

    # Internal state
    _history: list[ChatMessage] = field(default_factory=list, repr=False)
    _total_tokens: int = field(default=0, repr=False)
    _host: str = field(default="", repr=False)
    _is_thinking_model: bool | None = field(default=None, repr=False)

    def __post_init__(self):
        if not self._host:
            if self.provider == "llamacpp":
                self._host = get_llamacpp_host()
            else:
                self._host = get_ollama_host()

    def reset(self) -> None:
        """Clear conversation history for the next probe."""
        self._history = []

    async def chat(
        self,
        messages: list[tuple[str, str]],
        temperature: float | None = None,
    ) -> str:
        """Send a full conversation and get the final response.

        This is the primary method for single-shot probes.
        Resets history, sends all messages, returns the assistant's reply.

        Args:
            messages: List of (role, content) tuples.
            temperature: Override default temperature.

        Returns:
            The model's response text.
        """
        self.reset()
        for role, content in messages:
            self._history.append(ChatMessage(role=role, content=content))

        return await self._complete(temperature=temperature)

    async def send(
        self,
        content: str,
        role: str = "user",
        temperature: float | None = None,
    ) -> str:
        """Send a single message and get the response.

        This preserves conversation history, enabling multi-turn probes.

        Args:
            content: The message text.
            role: Usually "user". Can be "system" for mid-conversation system prompts.
            temperature: Override default temperature.

        Returns:
            The model's response text.
        """
        self._history.append(ChatMessage(role=role, content=content))
        return await self._complete(temperature=temperature)

    async def _complete(self, temperature: float | None = None) -> str:
        """Send current history to model and get response."""
        temp = temperature if temperature is not None else self.temperature

        if self.provider == "ollama":
            return await self._ollama_chat(temp)
        elif self.provider == "llamacpp":
            return await self._llamacpp_chat(temp)
        else:
            raise NotImplementedError(f"Provider {self.provider} not yet supported for ChatClient")

    async def _detect_thinking_model(self) -> bool:
        """Auto-detect if a model supports thinking/CoT via Ollama /api/show.

        Checks the 'capabilities' field for 'thinking'. Results are cached
        per model name so the API is only called once per model.
        """
        if self._is_thinking_model is not None:
            return self._is_thinking_model

        if self.model_name in _thinking_model_cache:
            self._is_thinking_model = _thinking_model_cache[self.model_name]
            return self._is_thinking_model

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http:
                resp = await http.post(
                    f"{self._host}/api/show",
                    json={"name": self.model_name},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    capabilities = data.get("capabilities", [])
                    is_thinking = "thinking" in capabilities
                    _thinking_model_cache[self.model_name] = is_thinking
                    self._is_thinking_model = is_thinking
                    return is_thinking
        except (httpx.ConnectError, httpx.TimeoutException):
            pass

        self._is_thinking_model = False
        return False

    async def _ollama_chat(self, temperature: float) -> str:
        """Call Ollama /api/chat endpoint."""
        url = f"{self._host}/api/chat"

        # Auto-detect thinking models and disable CoT to prevent timeouts.
        # Gauntlet tests behavioral reliability, not reasoning chains —
        # thinking mode wastes tokens and causes massive slowdowns.
        is_thinking = await self._detect_thinking_model()

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in self._history
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": self.max_tokens,
            },
        }

        if is_thinking:
            payload["think"] = False

        # Use httpx.Timeout for fine-grained control:
        # - connect: 30s to establish connection
        # - read: full timeout for slow model generation
        # - write: 30s to send request
        # - pool: 30s to acquire connection from pool
        timeout = httpx.Timeout(
            connect=30.0,
            read=self.timeout_s,
            write=30.0,
            pool=30.0,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                resp = await http.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ReadTimeout:
            raise TimeoutError(
                f"Model {self.model_name} did not respond within {self.timeout_s:.0f}s. "
                f"Thinking models need more time. Try --timeout 900"
            )

        content = data.get("message", {}).get("content", "")

        # Track tokens (includes thinking tokens for thinking models)
        eval_count = data.get("eval_count", 0)
        self._total_tokens += eval_count

        # If content is empty but tokens were generated, the model likely
        # exhausted its token budget on internal thinking (e.g. qwen3.5).
        if not content.strip() and eval_count > 0:
            # Try to extract from thinking field if available
            thinking = data.get("message", {}).get("thinking", "")
            if thinking:
                content = f"[thinking model exhausted token budget -- {eval_count} tokens used for reasoning, no visible output]"

        # Add assistant message to history
        self._history.append(ChatMessage(role="assistant", content=content))

        return content

    async def _llamacpp_chat(self, temperature: float) -> str:
        """Call llama.cpp server via OpenAI-compatible /v1/chat/completions.

        llama-server (llama.cpp) exposes an OpenAI-compatible API by default.
        Start it with: llama-server -m model.gguf --port 8080

        Set LLAMACPP_HOST env var to override the default http://localhost:8080.
        The model_name field is sent in the request but llama-server typically
        ignores it (it serves whatever model was loaded at startup).
        """
        url = f"{self._host}/v1/chat/completions"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in self._history
            ],
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }

        timeout = httpx.Timeout(
            connect=30.0,
            read=self.timeout_s,
            write=30.0,
            pool=30.0,
        )

        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                resp = await http.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ReadTimeout:
            raise TimeoutError(
                f"llama.cpp server did not respond within {self.timeout_s:.0f}s. "
                f"Model may be too large for available memory."
            )
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot connect to llama.cpp server at {self._host}. "
                f"Start it with: llama-server -m model.gguf --port 8080"
            )

        # OpenAI format: choices[0].message.content
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("llama.cpp returned no choices")

        content = choices[0].get("message", {}).get("content", "")

        # Track tokens from usage field
        usage = data.get("usage", {})
        self._total_tokens += usage.get("completion_tokens", 0)

        self._history.append(ChatMessage(role="assistant", content=content))
        return content

    @property
    def history(self) -> list[ChatMessage]:
        """Get conversation history (read-only view)."""
        return list(self._history)

    @property
    def turn_count(self) -> int:
        """Number of assistant responses in this conversation."""
        return sum(1 for m in self._history if m.role == "assistant")

    @property
    def total_tokens(self) -> int:
        """Total tokens generated across all turns."""
        return self._total_tokens
