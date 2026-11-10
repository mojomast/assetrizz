"""Hermes plugin entrypoint for assetrizz. Registers the skill and tools."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from assetrizz_plugin import PLUGIN_ID, SKILL_ID  # noqa: E402

# Injected via ctx.register_system_prompt_section so the agent can find the
# tools when Hermes Tool Search defers them. Keep this short.
ASSETRIZZ_SYSTEM_PROMPT_SECTION = (
    "Assetrizz is a local 2D game-asset library. Drive it ONLY with "
    "assetrizz_search and assetrizz_scene (toolset assetrizz). If those tools "
    "are not in your visible list, call "
    f'tool_search(["assetrizz"]) or skill_view("{SKILL_ID}"), then use them. '
    "Search first, then create a scene and place/tile assets by slug or id. "
    "render writes a PNG under the export dir — do not embed full images. "
    "The compose pane live-previews the current scene."
)


def register(ctx) -> None:
    """Register skills/<name>/SKILL.md and the assetrizz_* tools.

    Keep this fast. Pillow, SQLite restores, and compositing happen inside
    tool calls, not during load.
    """
    skills_dir = Path(__file__).resolve().parent / "skills"
    if skills_dir.is_dir() and hasattr(ctx, "register_skill"):
        for child in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            skill_md = child / "SKILL.md"
            if skill_md.is_file():
                ctx.register_skill(child.name, skill_md)
    from assetrizz_plugin.tools import register_tools

    register_tools(ctx)
    if hasattr(ctx, "register_system_prompt_section"):
        try:
            ctx.register_system_prompt_section(
                "assetrizz-composer",
                ASSETRIZZ_SYSTEM_PROMPT_SECTION,
            )
        except Exception:
            pass
