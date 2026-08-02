"""OpenAI adapter.

Written against the `openai` Python SDK's Chat Completions surface, which is
the most stable target across SDK versions. Structured output uses
`response_format` with a strict JSON schema, falling back to plain JSON mode if
the model rejects the schema form.

Model comes from OPENAI_MODEL so this never hard-codes a guess that ages badly.
"""

import json
from typing import Any

from intentdesk.config import settings
from intentdesk.llm import LLMError, Refusal


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self._client: Any = None

    def available(self) -> bool:
        return bool(settings.openai_api_key)

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.openai_api_key)
        return self._client

    def _create(self, **kwargs: Any) -> Any:
        import openai

        try:
            return self._get_client().chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise LLMError(f"openai rejected the API key: {exc}") from exc
        except openai.NotFoundError as exc:
            raise LLMError(f"unknown model {settings.openai_model!r}: {exc}") from exc
        except openai.RateLimitError as exc:
            raise LLMError(f"openai rate limited: {exc}") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"openai returned {exc.status_code}: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError(f"could not reach openai: {exc}") from exc

    @staticmethod
    def _text_of(response: Any) -> str:
        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "content_filter":
            raise Refusal("content filter")
        refusal = getattr(choice.message, "refusal", None)
        if refusal:
            raise Refusal(str(refusal))
        text = (choice.message.content or "").strip()
        if not text:
            raise LLMError(f"empty response (finish_reason={choice.finish_reason})")
        return text

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        response = self._create(
            model=settings.openai_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return self._text_of(response)

    def complete_json(
        self, system: str, prompt: str, schema: dict, max_tokens: int = 1024
    ) -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        base = {"model": settings.openai_model, "max_tokens": max_tokens, "messages": messages}

        try:
            response = self._create(
                **base,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "result", "strict": True, "schema": schema},
                },
            )
        except LLMError:
            # Older or non-strict models reject the schema form; plain JSON mode
            # still constrains the output enough to parse and validate.
            response = self._create(**base, response_format={"type": "json_object"})

        raw = self._text_of(response)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"openai returned non-JSON: {raw[:200]}") from exc
