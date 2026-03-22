"""Wrapper Crapper CLI — Keep your shit together.

Discovery (what the agent sees):
    wc help <tool.yaml> [--scope s.yaml]                 # tree: groups + commands
    wc schema <tool.yaml> <group> [--scope s.yaml]       # TypeScript interfaces
    wc schema <tool.yaml> <group> <cmd> [--scope s.yaml] # single command interface

Enforcement (what actually happens):
    wc exec <tool.yaml> --scope s.yaml <group> <cmd> [--params '{}']  # wrapped call

Scope management:
    wc scope show|init|deny|allow|pin|unpin|hide <scope.yaml> ...
"""

import json

import click
from pathlib import Path

from wrappy_crappy.loader import load_tool
from wrappy_crappy.scope import ScopeConfig
from wrappy_crappy.render import render_tree_root, render_ts_group, render_ts_command
from wrappy_crappy.enforce import enforce_call, enforce_output, exec_wrapped


@click.group()
def cli():
    """Wrappy Crappy — Keep(s) your CLI shit together"""
    pass


# ---------------------------------------------------------------------------
# help — tree at root level only
# ---------------------------------------------------------------------------


@cli.command("interface")
@click.argument("tool_file", type=click.Path(exists=True))
@click.option("--scope", "scope_file", type=click.Path(exists=True), default=None)
def interface_cmd(tool_file, scope_file):
    """Tree overview: groups and command names (no args, no schemas)."""
    tool = load_tool(Path(tool_file))
    scope = ScopeConfig.load(Path(scope_file)) if scope_file else None
    click.echo(render_tree_root(tool, scope))


# ---------------------------------------------------------------------------
# schema — TypeScript interfaces for progressive discovery
# ---------------------------------------------------------------------------


@cli.command("schema")
@click.argument("tool_file", type=click.Path(exists=True))
@click.argument("group")
@click.argument("command", required=False)
@click.option("--scope", "scope_file", type=click.Path(exists=True), default=None)
def schema_cmd(tool_file, group, command, scope_file):
    """TypeScript interfaces — precise input/output contracts."""
    tool = load_tool(Path(tool_file))
    scope = ScopeConfig.load(Path(scope_file)) if scope_file else None

    if command:
        click.echo(render_ts_command(tool, group, command, scope))
    else:
        click.echo(render_ts_group(tool, group, scope))


# ---------------------------------------------------------------------------
# exec — runtime enforcement
# ---------------------------------------------------------------------------


@cli.command("exec")
@click.argument("tool_file", type=click.Path(exists=True))
@click.argument("group")
@click.argument("command")
@click.option(
    "--scope",
    "scope_file",
    type=click.Path(exists=True),
    required=True,
    help="Scope YAML (required for enforcement)",
)
@click.option("--params", "params_json", default="{}", help="Command params as JSON")
@click.option("--binary", default=None, help="Override the CLI binary name")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be executed without running"
)
def exec_cmd(tool_file, group, command, scope_file, params_json, binary, dry_run):
    """Execute a wrapped CLI call with scope enforcement.

    Rejects denied commands. Pins fixed params. Strips hidden output fields.
    """
    tool = load_tool(Path(tool_file))
    scope = ScopeConfig.load(Path(scope_file))

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as e:
        click.echo(f"error: invalid JSON params: {e}", err=True)
        raise SystemExit(1)

    # Check + transform
    allowed, enforced_params, reason = enforce_call(scope, tool, group, command, params)

    if not allowed:
        click.echo(json.dumps({"error": reason}))
        raise SystemExit(1)

    if dry_run:
        bin_name = binary or tool.name
        click.echo(
            f"[dry-run] {bin_name} {group} {command} --json '{json.dumps(enforced_params)}'"
        )
        if enforced_params != params:
            click.echo(
                f"[dry-run] pinned params applied: {json.dumps({k: v for k, v in enforced_params.items() if params.get(k) != v})}"
            )
        hidden = scope.get_hidden_outputs(group, command)
        if hidden:
            click.echo(f"[dry-run] output fields to strip: {hidden}")
        return

    exit_code, output = exec_wrapped(tool, scope, group, command, params, binary)
    click.echo(output)
    if exit_code != 0:
        raise SystemExit(exit_code)


# ---------------------------------------------------------------------------
# scope management
# ---------------------------------------------------------------------------


@cli.group("scope")
def scope_group():
    """Manage scope policy — deny, pin, hide."""
    pass


@scope_group.command("show")
@click.argument("scope_file", type=click.Path(exists=True))
def scope_show(scope_file):
    """Show current scope config."""
    scope = ScopeConfig.load(Path(scope_file))
    if scope.deny:
        click.echo("deny:")
        for d in scope.deny:
            click.echo(f"  - {d}")
    if scope.pin:
        click.echo("pin:")
        for cmd, pins in scope.pin.items():
            for k, v in pins.items():
                click.echo(f"  {cmd}.{k} = {v}")
    if scope.hide_output:
        click.echo("hide_output:")
        for cmd, fields in scope.hide_output.items():
            for f in fields:
                click.echo(f"  {cmd}.{f}")
    if scope.constraints:
        click.echo("constraints:")
        for grp, kvs in scope.constraints.items():
            for k, v in kvs.items():
                click.echo(f"  {grp}.{k} = {v}")
    if not any([scope.deny, scope.pin, scope.hide_output, scope.constraints]):
        click.echo("(empty scope — no restrictions)")


@scope_group.command("init")
@click.argument("scope_file", type=click.Path())
@click.option("--force", is_flag=True, help="Overwrite existing")
def scope_init(scope_file, force):
    """Create a default scope config."""
    path = Path(scope_file)
    if path.exists() and not force:
        click.echo(f"error: {path} exists (use --force)", err=True)
        raise SystemExit(1)
    scope = ScopeConfig(
        deny=["example.dangerous_command"],
        pin={"example.share": {"role": "reader"}},
        hide_output={},
        constraints={},
    )
    scope.save(path)
    click.echo(f"ok: created {path}")


@scope_group.command("deny")
@click.argument("scope_file", type=click.Path(exists=True))
@click.argument("command")
def scope_deny(scope_file, command):
    """Deny a command (group.command or group.*)."""
    if "." not in command:
        click.echo("error: use group.command format", err=True)
        raise SystemExit(1)
    path = Path(scope_file)
    scope = ScopeConfig.load(path)
    if command not in scope.deny:
        scope.deny.append(command)
        scope.save(path)
    click.echo(f"ok: denied {command}")


@scope_group.command("allow")
@click.argument("scope_file", type=click.Path(exists=True))
@click.argument("command")
def scope_allow(scope_file, command):
    """Remove a command from deny list."""
    path = Path(scope_file)
    scope = ScopeConfig.load(path)
    if command in scope.deny:
        scope.deny.remove(command)
        scope.save(path)
        click.echo(f"ok: allowed {command}")
    else:
        click.echo(f"ok: {command} was not denied")


@scope_group.command("pin")
@click.argument("scope_file", type=click.Path(exists=True))
@click.argument("command")
@click.argument("key")
@click.argument("value")
def scope_pin(scope_file, command, key, value):
    """Pin a parameter to a fixed value."""
    if "." not in command:
        click.echo("error: use group.command format", err=True)
        raise SystemExit(1)
    path = Path(scope_file)
    scope = ScopeConfig.load(path)
    scope.pin.setdefault(command, {})[key] = value
    scope.save(path)
    click.echo(f"ok: pinned {command}.{key} = {value}")


@scope_group.command("unpin")
@click.argument("scope_file", type=click.Path(exists=True))
@click.argument("command")
@click.argument("key")
def scope_unpin(scope_file, command, key):
    """Unpin a parameter."""
    path = Path(scope_file)
    scope = ScopeConfig.load(path)
    if command in scope.pin and key in scope.pin[command]:
        del scope.pin[command][key]
        if not scope.pin[command]:
            del scope.pin[command]
        scope.save(path)
        click.echo(f"ok: unpinned {command}.{key}")
    else:
        click.echo(f"ok: {command}.{key} was not pinned")


@scope_group.command("hide")
@click.argument("scope_file", type=click.Path(exists=True))
@click.argument("command")
@click.argument("field")
def scope_hide(scope_file, command, field):
    """Hide an output field from agent visibility."""
    if "." not in command:
        click.echo("error: use group.command format", err=True)
        raise SystemExit(1)
    path = Path(scope_file)
    scope = ScopeConfig.load(path)
    scope.hide_output.setdefault(command, [])
    if field not in scope.hide_output[command]:
        scope.hide_output[command].append(field)
    scope.save(path)
    click.echo(f"ok: hidden {command}.{field}")


def main():
    cli()
