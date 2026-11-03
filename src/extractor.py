"""LLM call 1 (document reading) and the shared OpenAI call wrapper.

This module owns:
- settings (API key, model, reasoning effort) read from env, then Streamlit secrets;
- one structured Responses API call with clear error mapping (shared with call 2);
- the document-reading call and its code checks are added in milestone 2.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

DEFAULT_MODEL = "gpt-5.2"
DEFAULT_REASONING_EFFORT = "medium"
REQUEST_TIMEOUT_SECONDS = 240.0

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """A user-visible failure of an LLM call. Never replaced by fabricated output."""


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    model: str
    reasoning_effort: str | None  # None = do not send the parameter


def _secret(name: str) -> str | None:
    """Environment first, then .streamlit/secrets.toml (local or Streamlit Cloud)."""
    value = os.environ.get(name)
    if value is not None:
        return value
    try:
        import streamlit as st

        value = st.secrets.get(name)  # raises if no secrets file exists
    except Exception:
        return None
    return None if value is None else str(value)


def load_settings() -> Settings:
    model = (_secret("MODEL_NAME") or "").strip() or DEFAULT_MODEL
    effort_raw = _secret("REASONING_EFFORT")
    if effort_raw is None:
        effort: str | None = DEFAULT_REASONING_EFFORT
    else:
        effort = effort_raw.strip().lower() or None  # empty string -> omit
    key = (_secret("OPENAI_API_KEY") or "").strip() or None
    return Settings(api_key=key, model=model, reasoning_effort=effort)


def make_client(settings: Settings) -> openai.OpenAI:
    if not settings.api_key:
        raise LLMError(
            "OPENAI_API_KEY is not configured. Set it as an environment variable or in "
            ".streamlit/secrets.toml (see .streamlit/secrets.toml.example)."
        )
    # One click = one attempt: no automatic retries.
    return openai.OpenAI(
        api_key=settings.api_key, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS
    )


def _map_api_error(exc: Exception, model: str) -> LLMError:
    if isinstance(exc, openai.AuthenticationError):
        return LLMError("OpenAI rejected the API key (authentication failed).")
    if isinstance(exc, openai.PermissionDeniedError):
        return LLMError(f"The API key's project has no permission to use model '{model}'.")
    if isinstance(exc, openai.NotFoundError):
        return LLMError(f"Model '{model}' was not found or is not available to this API project.")
    if isinstance(exc, openai.RateLimitError):
        code = getattr(exc, "code", None) or ""
        if "quota" in str(code) or "quota" in str(exc).lower():
            return LLMError("The OpenAI project has no remaining quota (check billing).")
        return LLMError("OpenAI rate limit reached. Wait a moment and click Check Documents again.")
    if isinstance(exc, openai.APITimeoutError):
        return LLMError("The OpenAI request timed out. Try again.")
    if isinstance(exc, openai.APIConnectionError):
        return LLMError("Could not connect to the OpenAI API (network error).")
    if isinstance(exc, openai.BadRequestError):
        return LLMError(f"OpenAI rejected the request: {getattr(exc, 'message', exc)}")
    if isinstance(exc, openai.APIStatusError):
        return LLMError(f"OpenAI API error (HTTP {exc.status_code}): {getattr(exc, 'message', exc)}")
    if isinstance(exc, (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError)):
        return LLMError(f"The model response was cut off or filtered: {exc}")
    if isinstance(exc, ValidationError):
        return LLMError("The model returned output that does not match the required schema.")
    return LLMError(f"Unexpected error calling OpenAI: {type(exc).__name__}: {exc}")


def _find_refusal(response: Any) -> str | None:
    for item in getattr(response, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return getattr(part, "refusal", None) or "refused"
    return None


def call_structured(
    client: Any,
    settings: Settings,
    *,
    instructions: str,
    user_input: str,
    text_format: type[T],
) -> T:
    """One Structured Outputs call via the Responses API. Raises LLMError on any failure."""
    kwargs: dict[str, Any] = dict(
        model=settings.model,
        instructions=instructions,
        input=user_input,
        text_format=text_format,
        store=False,
    )
    if settings.reasoning_effort:
        kwargs["reasoning"] = {"effort": settings.reasoning_effort}
    try:
        response = client.responses.parse(**kwargs)
    except LLMError:
        raise
    except Exception as exc:  # mapped to a clear, user-visible message
        raise _map_api_error(exc, settings.model) from exc

    status = getattr(response, "status", None)
    if status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) or "unknown reason"
        raise LLMError(f"The model response was incomplete ({reason}).")
    if status == "failed":
        raise LLMError(f"The model response failed: {getattr(response, 'error', None)}")
    refusal = _find_refusal(response)
    if refusal:
        raise LLMError(f"The model refused the request: {refusal}")
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        raise LLMError("The model returned no parsable structured output.")
    if not isinstance(parsed, text_format):
        raise LLMError("The model returned output of an unexpected type.")
    return parsed
