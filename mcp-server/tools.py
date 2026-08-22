"""The Odoo tools, ported from cf-odoo-mcp-server.

Behaviour deliberately matches that project so NOTES.md applies to both.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from pydantic import Field

import odoo
from config import ConfigError, ModelPolicy, load_servers
from odoo import OdooError, ServerConfig

# Applied when odoo_search_read is called without a limit. Odoo imposes none, so
# the unbounded read of a production model that follows would exhaust the
# caller's context long before it failed on its own.
DEFAULT_LIMIT = 50

Model = Annotated[str, Field(description="Odoo model name (e.g. 'res.partner', 'sale.order')")]
Server = Annotated[
    str | None,
    Field(description="Server name from config. Omitted, the default server is used."),
]
Domain = Annotated[
    list[str | list[Any]],
    Field(
        description=(
            "Search domain as a list of conditions. "
            "Example: [[\"is_company\", \"=\", true]]. "
            "Prefix operators '&', '|' and '!' may appear as bare strings."
        )
    ),
]
Ids = Annotated[list[int], Field(description="Record IDs")]

_servers: dict[str, ServerConfig] | None = None
_default: str = ""
_policy: ModelPolicy | None = None


def _config() -> tuple[dict[str, ServerConfig], str]:
    global _servers, _default
    if _servers is None:
        _servers, _default = load_servers()
    return _servers, _default


def _policy_of() -> ModelPolicy:
    global _policy
    if _policy is None:
        _policy = ModelPolicy()
    return _policy


def _target(name: str | None) -> ServerConfig:
    servers, default = _config()
    resolved = name or default
    server = servers.get(resolved)
    if server is None:
        raise ConfigError(
            f"Unknown server '{resolved}'. Available: " + ", ".join(servers)
        )
    return server


def _target_for(model: str, name: str | None) -> ServerConfig:
    """Resolve the server and refuse the call if the model is out of scope."""
    _policy_of().check(model)
    return _target(name)


def dumps(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _same_text(a: str, b: str) -> bool:
    """Compare two strings ignoring html markup and whitespace differences."""
    def strip(v: str) -> str:
        v = re.sub(r"<[^>]*>", "", v)
        v = v.replace("&nbsp;", " ").replace("&amp;", "&")
        return re.sub(r"\s+", " ", v).strip()

    return strip(a) == strip(b)


def fields_not_applied(requested: dict[str, Any], stored: dict[str, Any]) -> list[str]:
    """Compare what was written against what Odoo stored.

    Odoo discards writes to readonly fields without erroring, so a successful
    create or write proves nothing about whether the values landed.

    Best-effort by design: it reports a field only when the comparison is
    unambiguous. A false alarm would send an agent chasing a write that actually
    succeeded.
    """
    dropped: list[str] = []
    for field, want in requested.items():
        if field not in stored:
            continue
        # x2many command lists and nested writes have no comparable stored form.
        if isinstance(want, (list, dict)):
            continue

        got = stored[field]
        # A many2one reads back as [id, display_name]; compare against the id.
        if isinstance(got, list) and len(got) == 2 and isinstance(got[0], int):
            got = got[0]
        # Odoo stores an empty string as False.
        if want == "" and got is False:
            continue
        if got == want:
            continue
        # An html field normalises plain text on the way in -- "ok" is stored as
        # "<p>ok</p>". That is the value being applied, not dropped.
        if isinstance(want, str) and isinstance(got, str) and _same_text(got, want):
            continue

        dropped.append(field)
    return dropped


def read_back(
    server: ServerConfig, model: str, ids: list[int], values: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """Read back the fields just written, bounded so a large write does not
    turn one call into an unbounded read."""
    fields = list(values)
    if not fields or len(ids) > DEFAULT_LIMIT:
        return None
    return odoo.execute(server, model, "read", [ids], {"fields": fields})


def group_by(
    server: ServerConfig,
    model: str,
    domain: list[Any],
    groupby: list[str],
    aggregates: list[str],
    kwargs: dict[str, Any],
) -> Any:
    """Group-and-aggregate, across Odoo versions.

    `read_group` is gone in saas~19.4 while `formatted_read_group` replaces it;
    19.0 still has both. Most Odoo material documents the old name, so an agent
    left to pick a method itself reaches for the one that may not exist.
    """
    try:
        return odoo.execute(
            server, model, "formatted_read_group", [domain, groupby, aggregates], kwargs
        )
    except OdooError as exc:
        if "does not exist" not in str(exc):
            raise
        # Pre-17 signature: aggregates were plain field names, and `__count`
        # came back whether or not it was asked for.
        fields = [a.split(":")[0] for a in aggregates if a != "__count"]
        return odoo.execute(
            server, model, "read_group", [domain, fields, groupby], {**kwargs, "lazy": False}
        )
