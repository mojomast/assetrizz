"""Hermes 0.21.7-safe register_tool wrapper (no output_schema TypeError)."""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Callable

_UNEXPECTED_KEYWORD = re.compile(
    r"got an unexpected keyword argument '([^']+)'", re.IGNORECASE
)


def _signature_parameters(register: Callable) -> dict[str, inspect.Parameter]:
    try:
        return dict(inspect.signature(register).parameters)
    except (TypeError, ValueError):
        return {}


def _accepts(register: Callable, key: str, parameters: dict[str, inspect.Parameter]) -> bool:
    if not parameters:
        return True
    if key in parameters:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())


def call_register_tool(register: Callable, **kwargs: Any) -> None:
    parameters = _signature_parameters(register)
    dropped = {key for key in kwargs if not _accepts(register, key, parameters)}
    last_error: TypeError | None = None
    for _ in range(1 + len(kwargs)):
        payload = {k: v for k, v in kwargs.items() if k not in dropped}
        if "output_schema" in dropped and "output_schema" in kwargs:
            note = "output_schema=" + json.dumps(
                kwargs["output_schema"], sort_keys=True, separators=(",", ":")
            )
            desc = str(payload.get("description") or "")
            if "output_schema=" not in desc:
                payload["description"] = (desc + " " + note).strip()
        try:
            register(**payload)
            return
        except TypeError as exc:
            last_error = exc
            match = _UNEXPECTED_KEYWORD.search(str(exc))
            if match is None:
                raise
            name = match.group(1)
            if name not in kwargs or name in dropped:
                raise
            dropped.add(name)
    if last_error is not None:
        raise last_error
