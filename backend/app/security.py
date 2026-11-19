from __future__ import annotations

import hashlib
import hmac
import logging
import re
from typing import Annotated

from fastapi import Header, HTTPException, status

from backend.app.config import get_settings

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_A_NUMBER_RE = re.compile(
    r"\bA[-\s#]?\d{3}[-\s]?\d{3}[-\s]?\d{3}\b|\bA\d{8,9}\b|\b\d{3}-\d{3}-\d{3}\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"
)


async def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    expected = get_settings().gateway_api_key.get_secret_value()
    if x_api_key is None or not hmac.compare_digest(
        x_api_key.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


def sign_body(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, header: str) -> bool:
    expected = sign_body(secret, body)
    return hmac.compare_digest(expected, header)


def _scrub_pii(text: str) -> str:
    scrubbed = _SSN_RE.sub("[SSN]", text)
    scrubbed = _A_NUMBER_RE.sub("[A_NUMBER]", scrubbed)
    scrubbed = _EMAIL_RE.sub("[EMAIL]", scrubbed)
    scrubbed = _PHONE_RE.sub("[PHONE]", scrubbed)
    return scrubbed


class PIIScrubFilter(logging.Filter):
    """Mask SSN, A-Number, email, and phone patterns in log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        scrubbed = _scrub_pii(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = _scrub_pii(formatted)
            record.exc_info = None
        return True

