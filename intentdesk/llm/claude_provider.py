"""Claude adapter (Anthropic SDK).

Model defaults to `claude-opus-5`. Notes that shaped this file:

- Thinking is ON by default on Claude Opus 5, and `max_tokens` caps thinking
  *plus* response text. A budget sized for a 90-word draft would truncate, so
  the token ceiling below is deliberately generous and effort is set low.
- Disabling thinking would be cheaper still, but on this model it can emit tool
  calls as plain text and leak `<thinking>` tags into the response. Adaptive
  thinking at low effort is the recommended way to keep cost down.
- `temperature` / `top_p` / `top_k` are rejected with a 400 — steer by prompt.
- Safety classifiers can decline a request: HTTP 200 with
  `stop_reason: "refusal"`. Check that before reading `content`.
- Server-side fallbacks are opted into by default so a refusal is re-run on
  another model rather than lost.
"""

import json
from typing import Any

from intentdesk.config import settings
from intentdesk.llm import LLMError, Refusal

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Thinking shares max_tokens with the response, so leave real headroom even for
# short outputs.
MIN_BUDGET = 4000


class ClaudeProvider:
    name = "claude"

    def __init__(self) -> None:
        self._client: Any = None

    def available(self) -> bool:
        return bool(settings.anthropic_api_key)

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def _call(self, **kwargs: Any) -> Any:
        """Send the request, preferring server-side fallbacks.

        An SDK too old to know the parameter raises rather than silently
        dropping it, so retry once without it instead of failing the call.
        """
        client = self._get_client()
        try:
            return client.beta.messages.create(
                betas=[FALLBACK_BETA], fallbacks="default", **kwargs
            )
        except TypeError:
            return client.messages.create(**kwargs)
        except Exception as exc:
            if "fallback" not in str(exc).lower():
                raise
            return client.messages.create(**kwargs)

    def _request(self, system: str, prompt: str, max_tokens: int, output_config: dict) -> Any:
        import anthropic

        try:
            return self._call(
                model=settings.claude_model,
                max_tokens=max(max_tokens, MIN_BUDGET),
                system=system,
                thinking={"type": "adaptive"},
                output_config=output_config,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.NotFoundError as exc:
            raise LLMError(f"unknown model {settings.claude_model!r}: {exc}") from exc
        except anthropic.AuthenticationError as exc:
            raise LLMError(f"anthropic rejected the API key: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(f"anthropic rate limited: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"anthropic returned {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"could not reach anthropic: {exc}") from exc

    @staticmethod
    def _text_of(response: Any) -> str:
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise Refusal(f"category={getattr(details, 'category', None)}")
        parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        if not parts:
            raise LLMError(f"no text in response (stop_reason={response.stop_reason})")
        return "\n".join(parts).strip()

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        response = self._request(system, prompt, max_tokens, {"effort": "low"})
        return self._text_of(response)

    def complete_json(
        self, system: str, prompt: str, schema: dict, max_tokens: int = 1024
    ) -> dict:
        response = self._request(
            system,
            prompt,
            max_tokens,
            {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        raw = self._text_of(response)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"claude returned non-JSON despite a schema: {raw[:200]}") from exc
