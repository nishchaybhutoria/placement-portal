"""Opt-in development email output, isolated from telemetry (the design review 4.42)."""

from __future__ import annotations

import json
import logging
import os
import sys


def dev_email_output_enabled() -> bool:
    """Validate at startup, even when the worker's backend is injected.

    Missing environment/backend values cannot opt in through their unrelated
    runtime defaults. Only an explicitly configured development console may
    expose message content.
    """
    flag = os.environ.get("DEV_EMAIL_OUTPUT", "0")
    if flag not in {"0", "1"}:
        raise ValueError("DEV_EMAIL_OUTPUT must be 0 or 1")
    if flag == "0":
        return False
    if os.environ.get("APP_ENV") not in {"development", "test"}:
        raise ValueError("DEV_EMAIL_OUTPUT=1 requires APP_ENV=development or test")
    if os.environ.get("NOTIFICATION_BACKEND") != "console":
        raise ValueError("DEV_EMAIL_OUTPUT=1 requires NOTIFICATION_BACKEND=console")
    return True


class _EnvelopeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {"kind": "dev_email", **record.__dict__["dev_email"]},
            ensure_ascii=True,
            separators=(",", ":"),
        )


def dev_email_logger() -> logging.Logger | None:
    """Create a private handler; never install it on a registered/root logger."""
    if not dev_email_output_enabled():
        return None
    logger = logging.Logger("cds.dev_email", level=logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_EnvelopeFormatter())
    logger.addHandler(handler)
    return logger
