"""Shared registration and resolution for user-defined slash aliases."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class AliasResult:
    """Result of listing or registering aliases."""

    action: str
    aliases: list[dict] | None = None
    name: str | None = None
    target: str | None = None
    error: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class AliasResolution:
    """Resolved target and fixed arguments, before invocation arguments are appended."""

    command: str | None
    target: str | None
    alias_used: str
    error: str | None = None


def _normalize_quick_commands(value: object) -> dict:
    """Return the valid user command mapping used by stable configuration readers."""
    if not isinstance(value, dict):
        return {}
    return {
        str(name).lower(): entry
        for name, entry in value.items()
        if isinstance(name, str) and isinstance(entry, dict)
    }


def _quick_commands(config: object) -> dict:
    if isinstance(config, dict):
        value = config.get("quick_commands", {}) or {}
    else:
        value = getattr(config, "quick_commands", {}) or {}
    return _normalize_quick_commands(value)


def _parse_alias_args(args: str) -> tuple[str, str, str]:
    if not args or not args.strip():
        return "", "", ""
    space_idx = args.find(" ")
    if space_idx == -1:
        return 'usage: /alias /<name> "<expansion>"  (or /alias alone to list)', "", ""
    raw_name = args[:space_idx].strip()
    raw_body = args[space_idx + 1:].strip()
    name = raw_name[1:] if raw_name.startswith("/") else raw_name
    if not re.fullmatch(r"[a-zA-Z0-9_:/.-]+", name):
        return f'invalid alias name "{raw_name}" - use letters, digits, _, :, /, ., -', "", ""
    if not raw_body:
        return 'missing expansion body - wrap the target in quotes, e.g. /alias ss "/sessions"', "", ""
    body = raw_body
    if len(body) >= 2 and body[0] == body[-1] and body[0] in "\"'":
        body = body[1:-1]
    if not body:
        return "expansion body is empty after quote-stripping", "", ""
    body = body[1:] if body.startswith("/") else body
    return "", name, body


def _shadow_warning(name: str) -> str:
    from hermes_cli.commands import resolve_command

    if resolve_command(name) is not None:
        return f"\nWARNING: /{name} shadows a built-in command (user alias wins)"
    return ""


def manage_aliases(args: str, config: object, save_config_value: Callable[[str, object], bool]) -> AliasResult:
    """List or register aliases, delegating persistence to the active surface."""
    if not args or not args.strip():
        aliases = [
            {"name": name, "target": entry.get("target", "")}
            for name, entry in _quick_commands(config).items()
            if isinstance(entry, dict) and entry.get("type") == "alias"
        ]
        if not aliases:
            return AliasResult(
                action="error",
                error='No aliases configured - add one with: /alias /<name> "<expansion>"',
            )
        return AliasResult(action="list", aliases=sorted(aliases, key=lambda row: row["name"]))

    error, name, body = _parse_alias_args(args)
    if error:
        return AliasResult(action="error", error=error)

    target = f"/{body}"
    value = {"type": "alias", "target": target}
    if not save_config_value(f"quick_commands.{name}", value):
        return AliasResult(action="error", error="failed to write config.yaml")

    quick_commands = _quick_commands(config)
    quick_commands[name] = value
    if isinstance(config, dict):
        config["quick_commands"] = quick_commands
    else:
        setattr(config, "quick_commands", quick_commands)
    return AliasResult(action="set", name=name, target=target, warning=_shadow_warning(name))


def resolve_alias(command_text: str, quick_commands: object, *, max_depth: int = 32) -> AliasResolution | None:
    """Resolve an alias chain once; return ``None`` for non-alias commands."""
    parts = command_text.strip().split(maxsplit=1)
    if not parts:
        return None
    alias_used = parts[0].lstrip("/").lower()
    qcmds = _normalize_quick_commands(quick_commands)
    initial = qcmds.get(alias_used)
    if not isinstance(initial, dict) or initial.get("type") != "alias":
        return None

    invocation_args = parts[1].strip() if len(parts) > 1 else ""
    fixed_args = ""
    current = alias_used
    visited = {current}
    chain = [current]
    alias_hops = 0

    while True:
        entry = qcmds.get(current)
        raw_target = entry.get("target") if isinstance(entry, dict) else ""
        target_parts = str(raw_target or "").strip().lstrip("/").split(maxsplit=1)
        if not target_parts or not target_parts[0]:
            return AliasResolution(None, None, alias_used, f"alias '{current}' has empty target")

        target_name = target_parts[0]
        target_args = target_parts[1].strip() if len(target_parts) > 1 else ""
        fixed_args = " ".join(value for value in (target_args, fixed_args) if value)
        next_name = target_name.lower()
        next_entry = qcmds.get(next_name)
        alias_hops += 1

        if isinstance(next_entry, dict) and next_entry.get("type") == "alias":
            if next_name in visited:
                cycle = " -> ".join((*chain, next_name))
                return AliasResolution(None, None, alias_used, f"alias cycle detected: {cycle}")
            if alias_hops >= max_depth:
                return AliasResolution(None, None, alias_used, f"alias chain exceeds maximum depth ({max_depth})")
            visited.add(next_name)
            chain.append(next_name)
            current = next_name
            continue

        target = f"/{target_name} {fixed_args}".strip()
        command = f"{target} {invocation_args}".strip()
        return AliasResolution(command, target, alias_used)