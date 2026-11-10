"""Assetrizz Hermes plugin: search the asset library and compose scenes."""

from __future__ import annotations

__version__ = "0.1.0"
PLUGIN_ID = "assetrizz"
SKILL_ID = "assetrizz:assetrizz-composer"
MIN_HERMES = "0.23.0"
TOOLSET = PLUGIN_ID
# GitHub raw ref for on-demand PNGs. This plugin version ships as tag v0.1.0;
# after the release is tagged, that ref is the merge commit the tag points at.
ASSET_REF = "v0.1.0"
ASSET_REPO = "mojomast/assetrizz"
ASSET_HOST = "raw.githubusercontent.com"
BUNDLED_DB_SHA256 = "4db275d4d7348a8d88460f78b24ba9565e55d93cdb68f4a1b8a9673dfd54bc4d"
