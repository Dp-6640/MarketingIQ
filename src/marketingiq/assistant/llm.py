"""Talking to a language model: one interface, any OpenAI-compatible endpoint.

Gemini, Groq, OpenRouter and a local Ollama all accept the OpenAI chat-completions format,
so switching provider is configuration (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL). Tests use
`ScriptedModel`, which plays back fixed replies and never touches the network.
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI

from marketingiq.config import get_settings


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, exactly as the model wrote it


@dataclass(frozen=True)
class Reply:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def as_message(self) -> dict[str, Any]:
        """The reply as an assistant message to append to the conversation."""
        message: dict[str, Any] = {"role": "assistant", "content": self.text or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        return message


class ChatModel(Protocol):
    name: str

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply: ...


class OpenAICompatible:
    """Any endpoint that speaks OpenAI's chat-completions API."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 90.0):
        self.name = model
        self._model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=3)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            tool_choice="auto",
            temperature=0,
        )
        message = response.choices[0].message
        calls = [
            ToolCall(call.id, call.function.name, call.function.arguments or "{}")
            for call in message.tool_calls or []
            if call.type == "function"
        ]
        usage = response.usage
        return Reply(
            text=message.content,
            tool_calls=calls,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )


Script = Reply | Callable[[list[dict[str, Any]]], Reply]


class ScriptedModel:
    """Plays back replies in order; a callable step sees the conversation so far."""

    def __init__(self, steps: Sequence[Script], name: str = "scripted"):
        self.name = name
        self._steps = list(steps)
        self.seen: list[list[dict[str, Any]]] = []

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        self.seen.append(list(messages))
        if not self._steps:
            raise RuntimeError("the script ran out of replies")
        step = self._steps.pop(0)
        return step(messages) if callable(step) else step


def call(name: str, arguments: dict[str, Any], call_id: str = "") -> ToolCall:
    """A tool call for scripts and tests."""
    return ToolCall(call_id or f"call_{name}", name, json.dumps(arguments))


class ModelNotConfigured(RuntimeError):
    pass


def get_chat_model() -> OpenAICompatible:
    """The configured model. Local endpoints (Ollama) need no key; any other endpoint does."""
    settings = get_settings()
    local = "localhost" in settings.llm_base_url or "127.0.0.1" in settings.llm_base_url
    key = settings.llm_api_key.get_secret_value().strip() if settings.llm_api_key else ""
    if not key and not local:
        raise ModelNotConfigured(
            "LLM_API_KEY is not set. Add it to .env (see .env.example) to use the assistant."
        )
    key = key or "local"
    return OpenAICompatible(settings.llm_base_url, key, settings.llm_model)
