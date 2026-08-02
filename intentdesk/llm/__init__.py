"""LLM providers.

Two adapters behind one interface: OpenAI primary, Claude as the fallback, per
the operator's choice. Everything above this layer — analysis, drafting — talks
to `complete()` / `complete_json()` and never imports a vendor SDK directly.

Neither adapter is exercised on this box: no OPENAI_API_KEY, and the
ANTHROPIC_API_KEY present here is not in Anthropic's `sk-ant-` format. Treat the
first live call as the test.
"""

from typing import Optional, Protocol

from intentdesk.config import settings


class LLMError(RuntimeError):
    """Provider call failed in a way the caller should surface, not swallow."""


class Refusal(LLMError):
    """The model declined the request on safety grounds.

    Distinct from a transport failure: retrying the same prompt on the same
    provider will refuse again, so callers should fall back or skip.
    """


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str: ...

    def complete_json(
        self, system: str, prompt: str, schema: dict, max_tokens: int = 1024
    ) -> dict: ...


def _build(name: str) -> Optional[Provider]:
    if name == "openai":
        from intentdesk.llm.openai_provider import OpenAIProvider

        return OpenAIProvider()
    if name == "gemini":
        from intentdesk.llm.gemini_provider import GeminiProvider

        return GeminiProvider()
    if name == "claude":
        from intentdesk.llm.claude_provider import ClaudeProvider

        return ClaudeProvider()
    return None


def chain() -> list[Provider]:
    """Providers in preference order, unavailable ones included.

    Kept in order rather than filtered so `status()` can report *why* a
    provider is not usable instead of silently omitting it.
    """
    names = [settings.llm_provider, settings.llm_fallback_provider]
    seen: list[str] = []
    for n in names:
        n = (n or "").strip().lower()
        if n and n not in seen:
            seen.append(n)
    return [p for p in (_build(n) for n in seen) if p is not None]


def active() -> Optional[Provider]:
    for p in chain():
        if p.available():
            return p
    return None


def status() -> dict:
    providers = [
        {"name": p.name, "available": p.available(), "order": i + 1}
        for i, p in enumerate(chain())
    ]
    return {
        "providers": providers,
        "active": next((p["name"] for p in providers if p["available"]), None),
    }


def complete(system: str, prompt: str, max_tokens: int = 1024) -> str:
    """Try each configured provider in order; fall through on refusal or error."""
    errors: list[str] = []
    for provider in chain():
        if not provider.available():
            errors.append(f"{provider.name}: no API key configured")
            continue
        try:
            return provider.complete(system, prompt, max_tokens)
        except Refusal as exc:
            errors.append(f"{provider.name}: refused ({exc})")
        except LLMError as exc:
            errors.append(f"{provider.name}: {exc}")
    raise LLMError("; ".join(errors) or "no LLM provider configured")


def validate_against(result: dict, schema: dict) -> None:
    """Check required keys and enums.

    Providers can silently fall back to free-form JSON when a schema is
    rejected, returning plausible output with invented keys and values. Without
    this check that output flows straight into the database looking correct.
    """
    if not isinstance(result, dict):
        raise LLMError(f"expected a JSON object, got {type(result).__name__}")

    missing = [k for k in schema.get("required", []) if k not in result]
    if missing:
        raise LLMError(
            f"response is missing required field(s) {missing} — the schema was "
            f"probably rejected and the provider fell back to free-form JSON. "
            f"Got keys: {sorted(result)}"
        )

    for field, spec in (schema.get("properties") or {}).items():
        allowed = spec.get("enum")
        if allowed and field in result and result[field] not in allowed:
            raise LLMError(f"{field}={result[field]!r} is not one of {allowed}")


def complete_json(system: str, prompt: str, schema: dict, max_tokens: int = 1024) -> dict:
    errors: list[str] = []
    for provider in chain():
        if not provider.available():
            errors.append(f"{provider.name}: no API key configured")
            continue
        try:
            result = provider.complete_json(system, prompt, schema, max_tokens)
            validate_against(result, schema)
            return result
        except Refusal as exc:
            errors.append(f"{provider.name}: refused ({exc})")
        except LLMError as exc:
            errors.append(f"{provider.name}: {exc}")
    raise LLMError("; ".join(errors) or "no LLM provider configured")
