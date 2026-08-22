"""Odoo MCP server for ChatGPT, reached through an OpenAI Secure MCP Tunnel.

The tunnel runs beside this process inside the same network as Odoo and opens
only an outbound HTTPS connection, so Odoo never needs a public address. That
is the whole reason this exists next to cf-odoo-mcp-server, which runs on
Cloudflare and therefore cannot reach a private Odoo at all.
"""

from __future__ import annotations

import hmac
import os
from typing import Annotated, Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

import odoo
from config import ConfigError
from tools import (
    DEFAULT_LIMIT,
    Domain,
    Ids,
    Model,
    Server,
    _config,
    _policy_of,
    _target,
    _target_for,
    dumps,
    fields_not_applied,
    group_by,
    read_back,
)

AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN", "").strip()
PUBLIC_PATHS = ("/healthz",)

mcp = FastMCP(
    "odoo",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8000")),
    streamable_http_path="/mcp",
    stateless_http=True,
)


def run(fn) -> str:
    """Surface failures as tool errors rather than transport errors, so the
    model sees the message and can correct itself."""
    try:
        return dumps(fn())
    except Exception as exc:  # noqa: BLE001 - the message is the product here
        return f"Error: {exc}"


# --------------------------------------------------------------------- read


@mcp.tool()
def odoo_list_servers() -> str:
    """List all configured Odoo servers."""
    def go():
        servers, default = _config()
        return {"servers": list(servers), "default_server": default}
    return run(go)


@mcp.tool()
def odoo_version(server: Server = None) -> str:
    """Get Odoo server version information."""
    return run(lambda: odoo.version(_target(server)))


@mcp.tool()
def odoo_context(server: Server = None) -> str:
    """Who this server is connected as: user, company, timezone and language.
    Read this before working with dates -- Odoo stores datetimes in UTC."""
    def go():
        # Deliberately not subject to the model policy: this reads only the
        # identity the connection already has, and blocking it would leave an
        # agent guessing at its own timezone.
        target = _target(server)
        context = odoo.execute(target, "res.users", "context_get", [])
        rows = odoo.execute(
            target, "res.users", "read", [[context["uid"]]],
            {"fields": ["name", "login", "company_id", "company_ids"]},
        )
        user = rows[0] if rows else {}
        return {
            "server": target.name,
            "uid": context["uid"],
            "user": user.get("name"),
            "login": user.get("login"),
            "company": user.get("company_id"),
            "companies": user.get("company_ids", []),
            "timezone": context.get("tz"),
            "language": context.get("lang"),
            "note": (
                "Datetimes stored in Odoo are UTC. Convert to the timezone above "
                "only when presenting them to a person, and send UTC back."
            ),
        }
    return run(go)


@mcp.tool()
def odoo_get_models(
    server: Server = None,
    filter: Annotated[
        str | None,
        Field(description="Only models whose technical or display name contains this text"),
    ] = None,
    limit: Annotated[int, Field(description="Maximum number of models to return")] = 200,
) -> str:
    """List the models available on this server, with their technical and display
    names. Transient wizard models and anything out of scope are left out.
    Reading ir.model needs the Access Rights group, so a least-privilege account
    cannot call this."""
    def go():
        target = _target(server)
        domain: list[Any] = [["transient", "=", False], ["abstract", "=", False]]
        if filter:
            domain = ["|", ["model", "ilike", filter], ["name", "ilike", filter]] + domain

        models = odoo.execute(
            target, "ir.model", "search_read", [domain],
            {"fields": ["model", "name"], "order": "model", "limit": limit},
        )
        policy = _policy_of()
        in_scope = [m for m in models if policy.allows(m["model"])]
        return {
            "count": len(in_scope),
            "hidden_by_policy": len(models) - len(in_scope),
            "models": [{"model": m["model"], "name": m["name"]} for m in in_scope],
        }
    return run(go)


@mcp.tool()
def odoo_fields_get(
    model: Model,
    server: Server = None,
    attributes: Annotated[
        list[str] | None,
        Field(description="Field attributes to return (e.g. ['string', 'type', 'required'])"),
    ] = None,
) -> str:
    """Get field definitions for an Odoo model. Useful for understanding model structure."""
    def go():
        kwargs = {"attributes": attributes} if attributes else {}
        return odoo.execute(_target_for(model, server), model, "fields_get", [], kwargs)
    return run(go)


@mcp.tool()
def odoo_search_count(model: Model, domain: Domain = [], server: Server = None) -> str:
    """Count records matching a search domain in an Odoo model."""
    def go():
        return odoo.execute(_target_for(model, server), model, "search_count", [domain])
    return run(go)


@mcp.tool()
def odoo_search_read(
    model: Model,
    domain: Domain = [],
    fields: Annotated[
        list[str] | None, Field(description="Field names to return. Omit for all fields.")
    ] = None,
    offset: Annotated[int, Field(description="Number of records to skip")] = 0,
    limit: Annotated[
        int,
        Field(
            description=(
                f"Maximum number of records to return. Defaults to {DEFAULT_LIMIT}; "
                "raise it deliberately, since an unbounded read of a large model "
                "returns everything."
            )
        ),
    ] = DEFAULT_LIMIT,
    order: Annotated[
        str | None, Field(description="Sort order (e.g. 'name asc, id desc')")
    ] = None,
    server: Server = None,
) -> str:
    """Search and read records from an Odoo model. Returns records matching the
    search domain with the specified fields."""
    def go():
        kwargs: dict[str, Any] = {"offset": offset, "limit": limit}
        if fields:
            kwargs["fields"] = fields
        if order:
            kwargs["order"] = order
        return odoo.execute(_target_for(model, server), model, "search_read", [domain], kwargs)
    return run(go)


@mcp.tool()
def odoo_read(
    model: Model,
    ids: Ids,
    fields: Annotated[list[str] | None, Field(description="Field names to return")] = None,
    server: Server = None,
) -> str:
    """Read specific records by their IDs from an Odoo model. IDs that do not
    exist are dropped silently rather than raising."""
    def go():
        kwargs = {"fields": fields} if fields else {}
        return odoo.execute(_target_for(model, server), model, "read", [ids], kwargs)
    return run(go)


@mcp.tool()
def odoo_read_group(
    model: Model,
    groupby: Annotated[
        list[str],
        Field(description="Fields to group by. A date field may carry a granularity, e.g. 'date_order:month'."),
    ],
    domain: Domain = [],
    aggregates: Annotated[
        list[str],
        Field(description="What to compute per group: '__count', or 'field:agg' such as 'amount_total:sum'."),
    ] = ["__count"],
    limit: Annotated[int | None, Field(description="Maximum number of groups")] = None,
    offset: Annotated[int, Field(description="Number of groups to skip")] = 0,
    order: Annotated[str | None, Field(description="Sort order over the grouped result")] = None,
    server: Server = None,
) -> str:
    """Group records and aggregate over them -- counts, sums, averages per group.
    Far cheaper than reading every record and tallying them yourself."""
    def go():
        kwargs: dict[str, Any] = {"offset": offset}
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return group_by(_target_for(model, server), model, domain, groupby, aggregates, kwargs)
    return run(go)


@mcp.tool()
def odoo_execute(
    model: Model,
    method: Annotated[str, Field(description="Method name to call")],
    args: Annotated[list[Any], Field(description="Positional arguments for the method")] = [],
    kwargs: Annotated[dict[str, Any], Field(description="Keyword arguments for the method")] = {},
    server: Server = None,
) -> str:
    """Execute any public method on an Odoo model. Use this for methods not
    covered by the other tools. Odoo refuses private methods over RPC."""
    def go():
        return odoo.execute(_target_for(model, server), model, method, args, kwargs)
    return run(go)


# -------------------------------------------------------------------- write


@mcp.tool()
def odoo_create(
    model: Model,
    values: Annotated[
        dict[str, Any],
        Field(description="Field values for the new record, e.g. {'name': 'New Partner'}"),
    ],
    server: Server = None,
) -> str:
    """Create a new record in an Odoo model. Returns the new id along with the
    written fields read back, and lists any field Odoo did not store."""
    def go():
        target = _target_for(model, server)
        new_id = odoo.execute(target, model, "create", [values])

        rows = read_back(target, model, [new_id], values)
        record = rows[0] if rows else None
        if not record:
            return {"id": new_id}

        dropped = fields_not_applied(values, record)
        result: dict[str, Any] = {"id": new_id, "record": record}
        if dropped:
            result["fields_not_applied"] = dropped
            result["warning"] = (
                "Odoo did not store these fields. They are usually readonly or "
                "computed; check odoo_fields_get before writing them again."
            )
        return result
    return run(go)


@mcp.tool()
def odoo_write(
    model: Model,
    ids: Annotated[list[int], Field(description="Record IDs to update")],
    values: Annotated[dict[str, Any], Field(description="Field values to update")],
    server: Server = None,
) -> str:
    """Update existing records in an Odoo model. Returns the written fields read
    back, and lists any field Odoo did not store."""
    def go():
        target = _target_for(model, server)
        written = odoo.execute(target, model, "write", [ids, values])

        rows = read_back(target, model, ids, values)
        if rows is None:
            return {"written": written}

        dropped = sorted({f for row in rows for f in fields_not_applied(values, row)})
        result: dict[str, Any] = {"written": written, "records": rows}
        if dropped:
            result["fields_not_applied"] = dropped
            result["warning"] = (
                "Odoo did not store these fields on at least one record. They "
                "are usually readonly or computed; check odoo_fields_get."
            )
        return result
    return run(go)


@mcp.tool()
def odoo_delete(
    model: Model,
    ids: Annotated[list[int], Field(description="Record IDs to delete")],
    server: Server = None,
) -> str:
    """Delete records from an Odoo model. This cannot be undone."""
    def go():
        return odoo.execute(_target_for(model, server), model, "unlink", [ids])
    return run(go)


# ---------------------------------------------------------------- transport


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


class BearerAuthMiddleware:
    """Require a bearer token on every path except PUBLIC_PATHS."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "") in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        supplied = headers.get("authorization", "")
        prefix = "Bearer "
        ok = supplied.startswith(prefix) and hmac.compare_digest(
            supplied[len(prefix):].strip(), self.token
        )
        if not ok:
            response = JSONResponse(
                {"error": "unauthorized", "detail": "missing or invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="odoo-mcp"'},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def build_app():
    app = mcp.streamable_http_app()
    return BearerAuthMiddleware(app, AUTH_TOKEN) if AUTH_TOKEN else app


if __name__ == "__main__":
    try:
        servers, default = _config()
        summary = f"servers={list(servers)} default={default}"
    except ConfigError as exc:
        summary = f"NOT CONFIGURED: {exc}"

    print(
        f"odoo-mcp: {summary} "
        f"auth={'bearer' if AUTH_TOKEN else 'DISABLED (no MCP_AUTH_TOKEN)'}",
        flush=True,
    )
    uvicorn.run(
        build_app(),
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
        log_level=os.environ.get("UVICORN_LOG_LEVEL", "info"),
    )
