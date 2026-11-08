"""Logging configuration with secret redaction.

All log records pass through ``RedactingFilter`` which masks common credential
shapes (GitHub tokens, Anthropic keys, bearer tokens, URL passwords) so that
secrets never reach log output even if accidentally interpolated.
"""
from __future__ import annotations

import logging
import re

from app.core.config import settings

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "gh*_***REDACTED***"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github_pat_***REDACTED***"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), "sk-ant-***REDACTED***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***REDACTED***"),
    (re.compile(r"(?i)((?:password|secret|token|api_key)\s*[=:]\s*)\S+"), r"\1***REDACTED***"),
    (re.compile(r"(://[^:/\s]+:)[^@\s]+@"), r"\1***@"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - malformed record
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_testpilot_configured", False):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._testpilot_configured = True  # type: ignore[attr-defined]
