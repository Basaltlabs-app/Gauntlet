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

from gauntlet.core.config import (
    get_api_key,
    get_llamacpp_host,
    get_lmstudio_host,
    get_ollama_host,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
)

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
            elif self.provider == "lmstudio":
                self._host = get_lmstudio_host()
            elif self.provider in (PROVIDER_OPENAI, PROVIDER_ANTHROPIC, PROVIDER_GOOGLE):
                # Cloud providers use hardcoded endpoints; _host is unused.
                self._host = ""
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
        elif self.provider == "lmstudio":
            return await self._lmstudio_chat(temp)
        elif self.provider == PROVIDER_OPENAI:
            return await self._openai_chat(temp)
        elif self.provider == PROVIDER_ANTHROPIC:
            return await self._anthropic_chat(temp)
        elif self.provider == PROVIDER_GOOGLE:
            return await self._google_chat(temp)
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

    async def _lmstudio_chat(self, temperature: float) -> str:
        """Call LM Studio's local server via OpenAI-compatible /v1/chat/completions.

        LM Studio exposes an OpenAI-compatible API on port 1234 by default.
        Override with the LMSTUDIO_HOST env var (some users run on custom
        ports). The model_name maps to whichever model is currently loaded
        in LM Studio — use `gauntlet discover` to list loaded models.
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
                f"LM Studio did not respond within {self.timeout_s:.0f}s. "
                f"Model may be too large for available memory, or still loading."
            )
        except httpx.ConnectError:
            raise ConnectionError(
                f"Cannot connect to LM Studio at {self._host}. "
                f"Open LM Studio, go to Developer > Local Server, and start the server. "
                f"Override the host with LMSTUDIO_HOST=http://localhost:<port>."
            )

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("LM Studio returned no choices")

        content = choices[0].get("message", {}).get("content", "")

        usage = data.get("usage", {})
        self._total_tokens += usage.get("completion_tokens", 0)

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

    async def _openai_chat(self, temperature: float) -> str:
        """Call OpenAI's Chat Completions API.

        Uses OPENAI_API_KEY from the environment. Supports any OpenAI
        model (gpt-4o, gpt-4o-mini, o1, o3, etc.). System messages pass
        through as-is in the messages array.
        """
        api_key = get_api_key(PROVIDER_OPENAI)
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Export it before running cloud benchmarks."
            )

        url = "https://api.openai.com/v1/chat/completions"

        payload: dict = {
            "model": self.model_name,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in self._history
            ],
            "stream": False,
        }
        # o-series reasoning models reject temperature/max_tokens in favor of
        # max_completion_tokens and default temp=1.
        is_reasoning = self.model_name.startswith(("o1", "o3", "o4"))
        if is_reasoning:
            payload["max_completion_tokens"] = self.max_tokens
        else:
            payload["temperature"] = temperature
            payload["max_tokens"] = self.max_tokens

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(connect=30.0, read=self.timeout_s, write=30.0, pool=30.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                resp = await http.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ReadTimeout:
            raise TimeoutError(
                f"OpenAI did not respond within {self.timeout_s:.0f}s."
            )

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("OpenAI returned no choices")
        content = choices[0].get("message", {}).get("content", "") or ""

        usage = data.get("usage", {})
        self._total_tokens += usage.get("completion_tokens", 0)

        self._history.append(ChatMessage(role="assistant", content=content))
        return content

    async def _anthropic_chat(self, temperature: float) -> str:
        """Call Anthropic's Messages API.

        Uses ANTHROPIC_API_KEY from the environment. Extracts system
        messages into Anthropic's dedicated `system` field (Anthropic
        doesn't accept role='system' inside the messages array).
        """
        api_key = get_api_key(PROVIDER_ANTHROPIC)
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it before running cloud benchmarks."
            )

        url = "https://api.anthropic.com/v1/messages"

        # Anthropic wants system as a top-level string; merge all system turns.
        system_parts = [m.content for m in self._history if m.role == "system"]
        chat_messages = [
            {"role": m.role, "content": m.content}
            for m in self._history
            if m.role in ("user", "assistant")
        ]

        payload: dict = {
            "model": self.model_name,
            "messages": chat_messages,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        timeout = httpx.Timeout(connect=30.0, read=self.timeout_s, write=30.0, pool=30.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                resp = await http.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ReadTimeout:
            raise TimeoutError(
                f"Anthropic did not respond within {self.timeout_s:.0f}s."
            )

        # Concatenate text blocks (ignore tool-use blocks for probe answers)
        parts = data.get("content", []) or []
        content = "".join(b.get("text", "") for b in parts if b.get("type") == "text")

        usage = data.get("usage", {})
        self._total_tokens += usage.get("output_tokens", 0)

        self._history.append(ChatMessage(role="assistant", content=content))
        return content

    async def _google_chat(self, temperature: float) -> str:
        """Call Google's Generative Language API (Gemini).

        Uses GOOGLE_API_KEY from the environment. Gemini uses role='model'
        instead of 'assistant' and puts system instructions in a dedicated
        `system_instruction` field.
        """
        api_key = get_api_key(PROVIDER_GOOGLE)
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not set. Export it before running cloud benchmarks."
            )

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model_name}:generateContent?key={api_key}"
        )

        system_parts = [m.content for m in self._history if m.role == "system"]
        contents = []
        for m in self._history:
            if m.role == "system":
                continue
            # Gemini expects 'user' | 'model' (not 'assistant')
            role = "model" if m.role == "assistant" else m.role
            contents.append({"role": role, "parts": [{"text": m.content}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }
        if system_parts:
            payload["system_instruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }

        timeout = httpx.Timeout(connect=30.0, read=self.timeout_s, write=30.0, pool=30.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                resp = await http.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ReadTimeout:
            raise TimeoutError(
                f"Google Gemini did not respond within {self.timeout_s:.0f}s."
            )

        # candidates[0].content.parts[0].text — but parts can be multiple
        candidates = data.get("candidates", [])
        if not candidates:
            # Safety block or empty response
            block_reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise ValueError(
                f"Gemini returned no candidates"
                f"{' (blocked: ' + block_reason + ')' if block_reason else ''}"
            )

        parts = (candidates[0].get("content") or {}).get("parts", []) or []
        content = "".join(p.get("text", "") for p in parts)

        usage = data.get("usageMetadata", {})
        self._total_tokens += usage.get("candidatesTokenCount", 0)

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
