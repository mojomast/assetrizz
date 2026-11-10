"""Dashboard entry that Hermes mounts at /api/plugins/assetrizz/.

The Desktop pane must call these routes through ctx.rest only. Never attach
authorization headers or dial a loopback server from the iframe.
"""

from __future__ import annotations

from assetrizz_plugin import pane

try:
    from fastapi import APIRouter, Request
except ImportError:  # pragma: no cover - fastapi is provided by Hermes
    APIRouter = None
    Request = None

if APIRouter is not None:
    router = APIRouter()

    @router.get("/health")
    def route_health():
        return pane.health()

    @router.get("/status")
    def route_status():
        return pane.status()

    @router.get("/scene")
    def route_scene(name: str | None = None):
        return pane.scene_view(name)

    @router.get("/preview")
    def route_preview(name: str | None = None, max_px: int = 960, since: str | None = None):
        return pane.preview(name, max_px=max_px, since=since)

    @router.get("/search")
    def route_search(
        q: str | None = None,
        style: str | None = None,
        category: str | None = None,
        tags: str | None = None,
        limit: int = 20,
        offset: int = 0,
        tileable: bool | None = None,
    ):
        return pane.search_view(
            {
                "q": q,
                "style": style,
                "category": category,
                "tags": tags,
                "limit": limit,
                "offset": offset,
                "tileable": tileable,
            }
        )

    @router.get("/asset")
    def route_asset(id: int | None = None, slug: str | None = None):
        return pane.asset_view({"id": id, "slug": slug})

    @router.get("/thumb")
    def route_thumb(id: int | None = None, slug: str | None = None, max_px: int = 96):
        return pane.thumb({"id": id, "slug": slug}, max_px=max_px)

    @router.post("/scene/select")
    async def route_select(request: Request):
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = (body or {}).get("name") or (body or {}).get("scene")
        return pane.scene_view(name)

    @router.get("/library/status")
    def route_library_status():
        return pane.library_view()

    @router.post("/library/download")
    async def route_library_download(request: Request):
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        return pane.library_download(body or {})

    @router.post("/library/cancel")
    async def route_library_cancel(request: Request):
        return pane.library_cancel()

    @router.post("/library/remove")
    async def route_library_remove(request: Request):
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        return pane.library_remove(body or {})

    @router.post("/library/clear-cache")
    async def route_library_clear_cache(request: Request):
        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        return pane.library_clear_cache(body or {})
else:  # pragma: no cover
    router = None

__all__ = ["router"]
