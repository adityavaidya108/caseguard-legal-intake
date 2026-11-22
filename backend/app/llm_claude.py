"""Claude extraction for immigration notices.

The extract() function must only ever receive redacted text. Raw PII must never
be passed to the Anthropic API.
"""

from __future__ import annotations

import logging
import time

import anthropic

from backend.app.config import get_settings
from backend.app.schemas import ExtractionResult

logger = logging.getLogger(__name__)

_TOOL_NAME = "extraction_result"
_SYSTEM_PROMPT = (
    "You are an immigration paralegal assistant. The document text contains "
    "placeholder tokens like [CLIENT_NAME_1] in place of real PII. Keep those "
    "tokens exactly as-is in draft_client_email and any other string fields. "
    "Never invent dates or facts that are not in the text. If a hearing was "
    "rescheduled or reset, hearing_date must be the NEW date; put the prior "
    "date in previous_hearing_date when stated. Sign every draft email as "
    '"Delgado & Mehta Immigration Law LLC". Never write placeholders like '
    "[Firm Name]; the only bracketed tokens allowed are the ones already in "
    "the input text."
)
_TIMEOUT_SECONDS = 60.0
_MAX_ATTEMPTS = 2  # initial try + 1 retry


def extract(redacted_text: str) -> ExtractionResult:
    settings = get_settings()
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=_TIMEOUT_SECONDS,
    )
    tools = [
        {
            "name": _TOOL_NAME,
            "description": (
                "Structured extraction of fields from a redacted immigration notice."
            ),
            "input_schema": ExtractionResult.model_json_schema(),
        }
    ]

    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        started = time.perf_counter()
        try:
            message = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                tools=tools,
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Extract structured fields from this redacted notice:\n\n"
                            f"{redacted_text}"
                        ),
                    }
                ],
            )
            latency_ms = (time.perf_counter() - started) * 1000
            usage = message.usage
            logger.info(
                "claude extract ok attempt=%s latency_ms=%.0f input_tokens=%s output_tokens=%s",
                attempt + 1,
                latency_ms,
                getattr(usage, "input_tokens", None),
                getattr(usage, "output_tokens", None),
            )

            for block in message.content:
                if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
                    return ExtractionResult.model_validate(block.input)

            raise RuntimeError("Claude response missing required tool call")
        except Exception as exc:
            last_error = exc
            latency_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "claude extract failed attempt=%s latency_ms=%.0f error_type=%s",
                attempt + 1,
                latency_ms,
                type(exc).__name__,
            )
            if attempt + 1 >= _MAX_ATTEMPTS:
                break

    assert last_error is not None
    raise last_error
