"""Server list and model policy, both read from the environment."""

from __future__ import annotations

import json
import os

from odoo import OdooError, ServerConfig

REQUIRED = ("url", "db", "username", "password")


class ConfigError(Exception):
    pass


def _validate(name: str, raw: object) -> ServerConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"ODOO_SERVERS: server '{name}' must be an object")
    for key in REQUIRED:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise ConfigError(f"ODOO_SERVERS: server '{name}' is missing '{key}'")
    return ServerConfig(name, raw["url"], raw["db"], raw["username"], raw["password"])


def load_servers() -> tuple[dict[str, ServerConfig], str]:
    """Returns the configured servers and the name of the default one."""
    raw = (os.environ.get("ODOO_SERVERS") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"ODOO_SERVERS is not valid JSON: {exc}") from exc

        entries = (parsed or {}).get("servers") or {}
        if not entries:
            raise ConfigError("ODOO_SERVERS contains no servers")

        servers = {name: _validate(name, cfg) for name, cfg in entries.items()}

        default = parsed.get("default_server")
        if default is not None and not isinstance(default, str):
            raise ConfigError("ODOO_SERVERS: 'default_server' must be a string")
        if default is not None and default not in servers:
            raise ConfigError(
                f"ODOO_SERVERS: default_server '{default}' is not one of: "
                + ", ".join(servers)
            )
        return servers, default or next(iter(servers))

    single = {key: os.environ.get(f"ODOO_{key.upper()}") for key in REQUIRED}
    if all(single.values()):
        return {"default": _validate("default", single)}, "default"

    raise ConfigError(
        "No Odoo server configured. Set ODOO_SERVERS, or all of "
        "ODOO_URL / ODOO_DB / ODOO_USERNAME / ODOO_PASSWORD."
    )


def _patterns(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


class ModelPolicy:
    """Which models the tools may touch.

    The Odoo account's own permissions are the boundary that cannot be bypassed;
    this is a second, coarser one an operator can set without touching Odoo.
    Both matter — see NOTES.md.
    """

    def __init__(self) -> None:
        self.allow = _patterns(os.environ.get("ALLOWED_MODELS"))
        self.block = _patterns(os.environ.get("BLOCKED_MODELS"))

    @staticmethod
    def _matches(pattern: str, model: str) -> bool:
        # `ir.*` matches by prefix; anything else must match exactly.
        if pattern.endswith("*"):
            return model.startswith(pattern[:-1])
        return pattern == model

    def allows(self, model: str) -> bool:
        if any(self._matches(p, model) for p in self.block):
            return False
        if not self.allow:
            return True
        return any(self._matches(p, model) for p in self.allow)

    def check(self, model: str) -> None:
        """Raise when a model is out of scope, naming the setting that put it there."""
        if self.allows(model):
            return
        reason = (
            "BLOCKED_MODELS"
            if any(self._matches(p, model) for p in self.block)
            else "ALLOWED_MODELS"
        )
        raise OdooError(f"Model '{model}' is out of scope for this server ({reason}).")
