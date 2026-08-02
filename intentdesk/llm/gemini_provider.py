"""Gemini adapter.

Talks to the Generative Language REST API with httpx rather than pulling in the
google SDK — one fewer dependency on a box that is short on RAM, and the wire
format is stable.

Gemini's structured output uses an OpenAPI-subset schema that rejects some
JSON Schema keywords (notably `additionalProperties`), so schemas are sanitised
before being sent and the call degrades to plain JSON mode if it still refuses.
"""

import json
from typing import Any

import httpx

from intentdesk.config import settings
from intentdesk.llm import LLMError, Refusal

BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Gemini blocks content by category; these finish reasons are refusals rather
# than failures, so retrying the same prompt will not help.
REFUSAL_REASONS = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}

UNSUPPORTED_SCHEMA_KEYS = {"additionalProperties", "$schema", "definitions", "$defs"}


def _sanitise(schema: Any) -> Any:
    """Convert JSON Schema to Gemini's OpenAPI subset.

    Two incompatibilities matter in practice: keywords like
    `additionalProperties` are rejected outright, and a union type such as
    `{"type": ["string", "null"]}` is not understood — it has to become a
    single type plus `nullable`. Sending either one gets the whole schema
    refused, which silently drops you into free-form JSON.
    """
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for key, value in schema.items():
            if key in UNSUPPORTED_SCHEMA_KEYS:
                continue
            if key == "type" and isinstance(value, list):
                concrete = [t for t in value if t != "null"]
                out["type"] = concrete[0] if concrete else "string"
                if "null" in value:
                    out["nullable"] = True
                continue
            out[key] = _sanitise(value)
        # Preserve author-declared key order; Gemini otherwise emits its own.
        if out.get("type") == "object" and "properties" in out:
            out.setdefault("propertyOrdering", list(out["properties"].keys()))
        return out
    if isinstance(schema, list):
        return [_sanitise(v) for v in schema]
    return schema


class GeminiProvider:
    name = "gemini"

    def available(self) -> bool:
        return bool(settings.gemini_api_key)

    def _post(self, payload: dict) -> dict:
        url = f"{BASE}/{settings.gemini_model}:generateContent"
        try:
            response = httpx.post(
                url,
                params={"key": settings.gemini_api_key},
                json=payload,
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"could not reach gemini: {exc}") from exc

        if response.status_code == 400:
            raise LLMError(f"gemini rejected the request: {response.text[:300]}")
        if response.status_code in (401, 403):
            raise LLMError(f"gemini rejected the API key: {response.text[:200]}")
        if response.status_code == 429:
            raise LLMError("gemini rate limited")
        if response.status_code >= 500:
            raise LLMError(f"gemini returned {response.status_code}")
        if response.status_code != 200:
            raise LLMError(f"gemini returned {response.status_code}: {response.text[:200]}")

        return response.json()

    @staticmethod
    def _text_of(data: dict) -> str:
        blocked = (data.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise Refusal(f"prompt blocked: {blocked}")

        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError("gemini returned no candidates")

        candidate = candidates[0]
        reason = candidate.get("finishReason")
        if reason in REFUSAL_REASONS:
            raise Refusal(f"finishReason={reason}")

        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            raise LLMError(f"gemini returned empty text (finishReason={reason})")
        return text

    def _payload(self, system: str, prompt: str, max_tokens: int) -> dict:
        return {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                # 2.5-flash is a thinking model and thinking is billed against
                # maxOutputTokens. Left on, a budget sized for a short answer is
                # consumed by reasoning and the reply truncates mid-sentence.
                # Classification and short drafts do not need it.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        return self._text_of(self._post(self._payload(system, prompt, max_tokens)))

    def complete_json(
        self, system: str, prompt: str, schema: dict, max_tokens: int = 1024
    ) -> dict:
        payload = self._payload(system, prompt, max_tokens)
        payload["generationConfig"].update(
            {
                "responseMimeType": "application/json",
                "responseSchema": _sanitise(schema),
            }
        )

        try:
            raw = self._text_of(self._post(payload))
        except LLMError as exc:
            if isinstance(exc, Refusal):
                raise
            # Schema rejected — plain JSON mode still constrains it enough.
            payload["generationConfig"].pop("responseSchema", None)
            raw = self._text_of(self._post(payload))

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"gemini returned non-JSON: {raw[:200]}") from exc
