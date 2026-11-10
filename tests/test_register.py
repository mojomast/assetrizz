from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"

# Import the strict loader via yaml; ruamel is used in the yaml test.
import yaml

from assetrizz_plugin import PLUGIN_ID, SKILL_ID, __version__
from assetrizz_plugin.tools import TOOL_NAMES, tool_specs
from tests.fakes import FakeCtx


def load_plugin():
    spec = importlib.util.spec_from_file_location("assetrizz_plugin_entry", PLUGIN / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_manifest_matches_registered_tools_and_skill():
    manifest = yaml.safe_load((PLUGIN / "plugin.yaml").read_text())
    ctx = FakeCtx()
    load_plugin().register(ctx)
    assert manifest["name"] == PLUGIN_ID == "assetrizz"
    assert manifest["version"] == __version__ == "0.1.0"
    assert manifest["requires_hermes"] == ">=0.23.0"
    assert manifest["requires_env"] == []
    assert manifest["provides_hooks"] == []
    assert list(ctx.tools) == list(manifest["provides_tools"]) == list(TOOL_NAMES)
    assert "assetrizz-composer" in ctx.skills
    skill = ctx.skills["assetrizz-composer"].read_text()
    assert SKILL_ID in skill and skill.startswith("---")
    assert "assetrizz-composer" in ctx.prompt_sections
    section = ctx.prompt_sections["assetrizz-composer"]["content"]
    assert "tool_search" in section
    assert "assetrizz_search" in section
    assert "assetrizz_scene" in section
    py = (PLUGIN / "pyproject.toml").read_text()
    assert f'version = "{manifest["version"]}"' in py
    for dep in manifest.get("python_dependencies") or []:
        assert "<" in dep and dep in py


def test_dashboard_manifest_points_at_plugin_api():
    data = json.loads((PLUGIN / "dashboard" / "manifest.json").read_text())
    assert data["name"] == "assetrizz"
    assert data["version"] == "0.1.0"
    api = PLUGIN / "dashboard" / data["api"]
    assert api.is_file()


def test_each_handler_returns_a_json_string():
    for spec in tool_specs():
        raw = spec["handler"]({"op": "not-a-real-op"})
        assert isinstance(raw, str)
        body = json.loads(raw)
        assert body["ok"] is False
        assert body["code"] == "invalid_op"
        assert body["fix"]
