"""SSRF-safe, allowlisted fetch of library PNGs from GitHub raw.

Downloads are pinned to ASSET_REF (the release this plugin version ships as),
verified with SHA-256 from the catalog, and cached under the plugin data dir.
A test fetcher can be injected; ASSETRIZZ_OFFLINE=1 refuses the network.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
import ssl
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

from assetrizz_plugin import ASSET_HOST, ASSET_REF, ASSET_REPO
from assetrizz_plugin.config import asset_mode, asset_ref
from assetrizz_plugin.errors import FetchError

# 5 MiB is well above the largest current library PNG and caps a runaway body.
MAX_ASSET_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT_S = 20
MAX_REDIRECTS = 3
_REF_OK = re.compile(r"^(?:v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?|[0-9a-f]{40})$")
_OFFLINE_ENV = "ASSETRIZZ_OFFLINE"

Fetcher = Callable[[str], bytes]
_fetcher: Fetcher | None = None



def set_fetcher(fn: Fetcher | None) -> None:
    """Install a test double. None restores the real HTTP client."""
    global _fetcher
    _fetcher = fn


def current_ref() -> str:
    ref = (asset_ref() or ASSET_REF).strip()
    if not _REF_OK.match(ref):
        raise FetchError(
            "asset_ref must be a vX.Y.Z tag or a 40-character commit SHA.",
            code="invalid_args",
            fix="Leave asset_ref at the default v0.1.0, or set a full commit SHA.",
        )
    return ref


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def normalize_asset_rel(stored: str) -> str:
    """Return a repo-relative ``assets/...png`` path with no library root required."""
    raw = (stored or "").strip().replace("\\", "/")
    if not raw:
        raise FetchError("Asset has no path.", code="not_found", fix="Search again and use a slug or id.")
    if raw.startswith("library/"):
        raw = "assets/" + raw[len("library/") :]
    if raw.startswith("/"):
        raise FetchError(
            "Absolute asset paths are not allowed.",
            code="path_escape",
            fix="Use a catalog slug or an assets/... path.",
        )
    if not raw.startswith("assets/"):
        raw = "assets/" + raw.lstrip("/")
    parts = raw.split("/")
    if ".." in parts or any(part in ("", ".", "..") for part in parts) or parts[0] != "assets":
        raise FetchError(
            "Asset path escaped the library assets/ prefix.",
            code="path_escape",
            fix="Use a slug from assetrizz_search.",
        )
    if not raw.lower().endswith(".png") or raw.lower().endswith(".png.png"):
        # allow exactly .png
        if not raw.lower().endswith(".png"):
            raise FetchError(
                "Only PNG assets from the library can be opened.",
                code="invalid_args",
                fix="Pass a library slug or id, not an arbitrary file path.",
            )
    return raw


def asset_url(rel: str, *, ref: str | None = None) -> str:
    """Build the allowlisted GitHub raw URL for one library PNG."""
    rel = normalize_asset_rel(rel)
    pin = ref or current_ref()
    # Encode each segment; slashes stay as path separators.
    path = "/" + ASSET_REPO + "/" + pin + "/" + "/".join(quote(part, safe="") for part in rel.split("/"))
    return f"https://{ASSET_HOST}{path}"


def is_allowlisted_url(url: str, *, ref: str | None = None) -> bool:
    try:
        assert_allowlisted(url, ref=ref)
    except FetchError:
        return False
    return True


def assert_allowlisted(url: str, *, ref: str | None = None) -> None:
    pin = ref or current_ref()
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise FetchError("Invalid asset URL.", code="fetch_failed") from exc
    if parsed.scheme != "https":
        raise FetchError("Asset downloads must use HTTPS.", code="fetch_failed")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise FetchError("Asset URL must not carry credentials, query, or fragment.", code="fetch_failed")
    host = (parsed.hostname or "").lower()
    if host != ASSET_HOST:
        raise FetchError(
            f"Refusing host {host or 'empty'} — only {ASSET_HOST} is allowed.",
            code="fetch_failed",
            fix="Do not change the asset host.",
        )
    prefix = f"/{ASSET_REPO}/{pin}/assets/"
    path = parsed.path or ""
    if not path.startswith(prefix) or not path.lower().endswith(".png"):
        raise FetchError(
            "Asset URL path is outside the pinned assets/ prefix.",
            code="path_escape",
            fix="Only files under assets/ at the pinned tag can be fetched.",
        )
    if ".." in path.split("/"):
        raise FetchError("Asset URL path escaped the prefix.", code="path_escape")


def _network_allowed() -> None:
    if os.environ.get(_OFFLINE_ENV, "").strip() in {"1", "true", "yes", "on"}:
        raise FetchError(
            "Network is disabled (ASSETRIZZ_OFFLINE). No asset was fetched.",
            code="offline",
            fix="Use a local library, or unset ASSETRIZZ_OFFLINE for on-demand fetches.",
        )
    mode = asset_mode()
    if mode == "offline":
        raise FetchError(
            "asset_mode is offline, so the plugin will not download assets.",
            code="offline",
            fix="Set asset_mode to on_demand or local, or place the PNG in the local library / cache.",
        )


def fetch_url(url: str, *, expected_sha256: str, ref: str | None = None) -> bytes:
    """Return the body of an allowlisted URL after SHA-256 verification."""
    assert_allowlisted(url, ref=ref)
    expected = (expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise FetchError(
            "Catalog is missing a SHA-256 for this asset.",
            code="hash_mismatch",
            fix="Use a catalog snapshot that includes sha256, or set a local library.",
        )
    # Honour offline / asset_mode even when a test fetcher is installed.
    _network_allowed()
    if _fetcher is not None:
        data = _fetcher(url)
    else:
        data = _http_get(url)
    if not isinstance(data, (bytes, bytearray)):
        raise FetchError("Fetcher returned a non-bytes body.", code="fetch_failed")
    data = bytes(data)
    if len(data) > MAX_ASSET_BYTES:
        raise FetchError(
            f"Asset exceeded the {MAX_ASSET_BYTES} byte cap.",
            code="payload_too_large",
            fix="Use a local library file, or report the oversize asset.",
        )
    digest = sha256_bytes(data)
    if digest != expected:
        raise FetchError(
            "SHA-256 of the downloaded PNG did not match the catalog.",
            code="hash_mismatch",
            fix="Delete the cached file if any, then retry. Do not use a mismatched file.",
        )
    return data


def _http_get(url: str) -> bytes:
    """HTTPS GET via the Hermes SSRF client when available; otherwise a pinned fallback."""
    hops = 0
    current = url
    while True:
        assert_allowlisted(current)
        status, body, location = _http_get_once(current)
        if status in {301, 302, 303, 307, 308}:
            hops += 1
            if hops > MAX_REDIRECTS or not location:
                raise FetchError("Too many or empty redirects while fetching an asset.", code="fetch_failed")
            # Resolve relative Location against the current URL, then re-allowlist (same host only).
            from urllib.parse import urljoin

            current = urljoin(current, location)
            continue
        if status != 200:
            raise FetchError(f"Asset download returned HTTP {status}.", code="fetch_failed")
        return body


def _http_get_once(url: str) -> tuple[int, bytes, str | None]:
    try:
        from tools.url_safety import create_ssrf_safe_client, is_safe_url  # type: ignore
    except Exception:
        create_ssrf_safe_client = None
        is_safe_url = None
    if create_ssrf_safe_client is not None:
        if callable(is_safe_url) and not is_safe_url(url):
            raise FetchError("Hermes SSRF guard rejected the asset URL.", code="fetch_failed")
        try:
            with create_ssrf_safe_client(
                timeout=FETCH_TIMEOUT_S, follow_redirects=False, trust_env=False
            ) as client:
                with client.stream("GET", url) as resp:
                    status = int(resp.status_code)
                    location = resp.headers.get("location")
                    if status in {301, 302, 303, 307, 308}:
                        return status, b"", location
                    if status != 200:
                        return status, b"", None
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > MAX_ASSET_BYTES:
                            raise FetchError(
                                f"Asset exceeded the {MAX_ASSET_BYTES} byte cap.",
                                code="payload_too_large",
                            )
                    return status, bytes(buf), None
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError(f"Asset download failed: {type(exc).__name__}.", code="fetch_failed") from exc
    return _stdlib_get_once(url)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if ip.is_reserved or ip.is_unspecified:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_blocked_ip(ip.ipv4_mapped)
    if not ip.is_global:
        return True
    networks = (
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("0.0.0.0/8"),
    )
    return any(ip in net for net in networks)


def _stdlib_get_once(url: str) -> tuple[int, bytes, str | None]:
    """Pinned HTTPS GET without ambient proxies or off-host redirects."""
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    path = parsed.path or "/"
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchError("Could not resolve the asset host.", code="fetch_failed") from exc
    ips: list[str] = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise FetchError("Refusing a non-global address for the asset host.", code="fetch_failed")
        ips.append(addr)
    if not ips:
        raise FetchError("Asset host resolved to no usable addresses.", code="fetch_failed")
    # Pin to the first validated address; SNI and cert still use the hostname.
    target_ip = ips[0]
    context = ssl.create_default_context()
    try:
        raw = socket.create_connection((target_ip, port), timeout=FETCH_TIMEOUT_S)
        sock = context.wrap_socket(raw, server_hostname=host)
    except OSError as exc:
        raise FetchError("Could not connect to the asset host.", code="fetch_failed") from exc
    try:
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: assetrizz-hermes-plugin\r\n"
            "Accept: image/png,application/octet-stream;q=0.9,*/*;q=0.1\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        sock.settimeout(FETCH_TIMEOUT_S)
        sock.sendall(request.encode("ascii"))
        buf = bytearray()
        while True:
            chunk = sock.recv(64 * 1024)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > MAX_ASSET_BYTES + 64 * 1024:
                raise FetchError(
                    f"Asset exceeded the {MAX_ASSET_BYTES} byte cap.",
                    code="payload_too_large",
                )
    finally:
        try:
            sock.close()
        except OSError:
            pass
    header, sep, body = bytes(buf).partition(b"\r\n\r\n")
    if not sep:
        raise FetchError("Asset host returned an empty or truncated response.", code="fetch_failed")
    lines = header.decode("iso-8859-1", errors="replace").split("\r\n")
    try:
        status = int(lines[0].split()[1])
    except (IndexError, ValueError) as exc:
        raise FetchError("Asset host returned a malformed status line.", code="fetch_failed") from exc
    location = None
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.lower() == "location":
            location = value.strip()
            break
    return status, body, location
