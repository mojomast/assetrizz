"""Minimal PluginContext stand-in for registration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class FakeCtx:
    def __init__(self) -> None:
        self.tools: list[str] = []
        self.tool_meta: dict[str, dict[str, Any]] = {}
        self.skills: dict[str, Path] = {}
        self.prompt_sections: dict[str, dict[str, str]] = {}
        self.hooks: dict[str, Callable] = {}

    def register_tool(
        self,
        name,
        toolset,
        schema,
        handler,
        check_fn=None,
        requires_env=None,
        is_async=False,
        description="",
        emoji="",
        override=False,
    ) -> None:
        self.tools.append(name)
        self.tool_meta[name] = {
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "description": description,
            "is_async": is_async,
            "override": override,
        }

    def register_skill(self, name: str, path: Path) -> None:
        self.skills[name] = Path(path)

    def register_system_prompt_section(self, name: str, content: str, **kwargs: Any) -> None:
        self.prompt_sections[name] = {"content": content, **kwargs}

    def register_hook(self, name: str, fn: Callable, **kwargs: Any) -> None:
        self.hooks[name] = fn
