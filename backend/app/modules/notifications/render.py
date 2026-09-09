"""Tolerant named-variable rendering for notification templates."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from string import Formatter

LOGGER = logging.getLogger(__name__)


class _BlankMissing(dict[str, object]):
    def __init__(self, values: Mapping[str, object], missing: set[str]) -> None:
        super().__init__({key: "" if value is None else value for key, value in values.items()})
        self._missing = missing

    def __missing__(self, key: str) -> str:
        self._missing.add(key)
        return ""


@dataclass(frozen=True, slots=True)
class RenderedText:
    text: str
    missing: tuple[str, ...]


def named_variables(template: str) -> tuple[str, ...]:
    """Return the named fields used by a template, rejecting non-named access."""
    fields: list[str] = []
    for _literal, field_name, _format_spec, _conversion in Formatter().parse(template):
        if field_name is None:
            continue
        if not field_name.isidentifier():
            raise ValueError("Template variables must be simple names such as {student}")
        fields.append(field_name)
    return tuple(dict.fromkeys(fields))


def render_text(
    template: str,
    context: Mapping[str, object],
    *,
    event_key: str,
    part: str,
) -> RenderedText:
    """Render one template part; absent values become blank and only warn.

    A malformed row can still be introduced outside the command path (for
    example by an operator restoring an old database).  It is treated with the
    same fail-open side-effect doctrine: render blank, warn, and let delivery
    continue rather than turning an email-copy problem into a stuck outbox.
    """
    missing: set[str] = set()
    try:
        text = template.format_map(_BlankMissing(context, missing))
    except (AttributeError, KeyError, ValueError) as error:
        LOGGER.warning(
            "Notification template could not be rendered; using blank text",
            extra={"event_key": event_key, "part": part, "error": str(error)},
        )
        return RenderedText(text="", missing=())
    for variable in sorted(missing):
        LOGGER.warning(
            "Notification template variable is missing; rendering it blank",
            extra={"event_key": event_key, "part": part, "variable": variable},
        )
    return RenderedText(text=text, missing=tuple(sorted(missing)))
