#!/usr/bin/env python3
"""Tiny read-only HTTP API for the asset catalog. Binds to 127.0.0.1 only."""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from query import search, stats
from db import ROOT


def _bool(qs, name):
    if name not in qs:
        return None
    v = qs[name][0].lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, obj, ctype="application/json"):
        body = json.dumps(obj, indent=2).encode() if ctype.endswith("json") else obj
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        qs = parse_qs(u.query)
        if path in ("/", "/health"):
            return self._send(200, {"ok": True, "service": "game-assets", "root": str(ROOT)})
        if path == "/stats":
            return self._send(200, stats())
        if path == "/search":
            try:
                limit = int(qs.get("limit", ["30"])[0])
                offset = int(qs.get("offset", ["0"])[0])
                size = int(qs["size"][0]) if "size" in qs else None
                min_size = int(qs["min_size"][0]) if "min_size" in qs else None
            except ValueError:
                return self._send(400, {"error": "bad numeric param"})
            rows = search(
                qs.get("q", [None])[0],
                category=qs.get("category", [None])[0],
                style=qs.get("style", [None])[0],
                subject=qs.get("subject", [None])[0],
                size=size,
                min_size=min_size,
                alpha=_bool(qs, "alpha"),
                tileable=_bool(qs, "tileable"),
                status=qs.get("status", ["ok"])[0],
                limit=min(limit, 200),
                offset=offset,
            )
            return self._send(200, {"count": len(rows), "results": rows})
        return self._send(404, {"error": "not found", "routes": ["/", "/health", "/search", "/stats"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"game-assets API on http://{args.host}:{args.port}/search?q=potion", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
