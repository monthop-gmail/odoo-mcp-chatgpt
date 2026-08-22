"""Odoo JSON-RPC client.

Odoo also speaks XML-RPC, and inside a container either would work. JSON-RPC is
used here because every behaviour this project documents was measured through
it — `formatted_read_group`, the readonly-field drops, the Odoo 19 field
renames. Keeping one transport keeps those notes applicable.
"""

from __future__ import annotations

import threading
from typing import Any

import httpx

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


class OdooError(Exception):
    """Raised for errors Odoo itself reports, as opposed to transport failures."""

    def __init__(self, message: str, data: Any = None):
        super().__init__(message)
        self.data = data


class ServerConfig:
    __slots__ = ("name", "url", "db", "username", "password")

    def __init__(self, name: str, url: str, db: str, username: str, password: str):
        self.name = name
        # A trailing slash would produce `https://host//jsonrpc`, which some
        # reverse proxies in front of Odoo reject.
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password


# uid cache, keyed by server name. The process is long-lived here (unlike the
# Workers build, where it lasted one isolate), so the lock matters: several MCP
# requests can be in flight at once.
_uids: dict[str, int] = {}
_uid_lock = threading.Lock()


def _rpc(base_url: str, service: str, method: str, args: list[Any]) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "id": 1,
        "params": {"service": service, "method": method, "args": args},
    }
    try:
        response = httpx.post(f"{base_url}/jsonrpc", json=payload, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise OdooError(f"Cannot reach Odoo at {base_url}: {exc}") from exc

    if response.status_code != 200:
        raise OdooError(
            f"Odoo returned HTTP {response.status_code} for {base_url}/jsonrpc"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise OdooError(
            f"Odoo returned a non-JSON response from {base_url}/jsonrpc. "
            "Check that the URL points at an Odoo instance."
        ) from exc

    if "error" in body:
        error = body["error"] or {}
        data = error.get("data") or {}
        # Odoo nests the useful message under data; the outer one is usually
        # just "Odoo Server Error".
        detail = data.get("message") or error.get("message") or "Unknown error"
        name = data.get("name")
        raise OdooError(f"{name}: {detail}" if name else detail, data)

    return body.get("result")


def _authenticate(server: ServerConfig) -> int:
    uid = _rpc(server.url, "common", "authenticate",
               [server.db, server.username, server.password, {}])
    if not uid:
        raise OdooError(
            f"Authentication failed for user '{server.username}' "
            f"on database '{server.db}'"
        )
    return int(uid)


def _uid(server: ServerConfig) -> int:
    with _uid_lock:
        cached = _uids.get(server.name)
    if cached is not None:
        return cached

    uid = _authenticate(server)
    with _uid_lock:
        _uids[server.name] = uid
    return uid


def _forget(server: ServerConfig) -> None:
    with _uid_lock:
        _uids.pop(server.name, None)


def execute(
    server: ServerConfig,
    model: str,
    method: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Call a method on an Odoo model.

    Retries once with a fresh uid: a cached uid can outlive the session it came
    from, and that failure is indistinguishable from a genuine permission error
    until we retry.
    """
    args = args or []
    kwargs = kwargs or {}

    def call(uid: int) -> Any:
        return _rpc(server.url, "object", "execute_kw",
                    [server.db, uid, server.password, model, method, args, kwargs])

    try:
        return call(_uid(server))
    except OdooError:
        _forget(server)
        return call(_uid(server))


def version(server: ServerConfig) -> dict[str, Any]:
    """Read the Odoo server version. Needs no authentication."""
    return _rpc(server.url, "common", "version", [])
