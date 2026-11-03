"""Dev check: one live Structured Outputs call with the configured model.

Usage (from the repo root, with OPENAI_API_KEY set or in .streamlit/secrets.toml):
    python scripts/check_api.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.extractor import LLMError, call_structured, load_settings, make_client  # noqa: E402


class Ping(BaseModel):
    form_type: str
    tax_year: int | None


def main() -> int:
    settings = load_settings()
    print(f"model={settings.model} reasoning_effort={settings.reasoning_effort or '(not sent)'}")
    try:
        client = make_client(settings)
        result = call_structured(
            client,
            settings,
            instructions="Return the form type and tax year printed in the text. Use null if absent.",
            user_input="SYNTHETIC SAMPLE. Form 1099-INT Interest Income. Tax year 2025.",
            text_format=Ping,
        )
    except LLMError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"OK: {result.model_dump()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
