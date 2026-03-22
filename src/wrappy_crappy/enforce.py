"""Runtime enforcement — the other half of the wrapper.

Discovery hides what shouldn't be seen.
Enforcement blocks what shouldn't be done.

Together: the agent can't discover forbidden tools, and even if it
guesses or hallucinates a call, the wrapper rejects it.

Enforcement actions:
  1. DENY  — reject calls to forbidden group.command
  2. PIN   — silently override params with fixed values
  3. STRIP — remove hidden fields from output JSON
"""

import json
import subprocess
import sys
from pathlib import Path

from wrapper_crapper.tool_def import ToolDef
from wrapper_crapper.scope import ScopeConfig


class ScopeViolation(Exception):
    def __init__(self, message: str, group: str, command: str):
        self.group = group
        self.command = command
        super().__init__(message)


def enforce_call(
    scope: ScopeConfig,
    tool: ToolDef,
    group_name: str,
    command_name: str,
    params: dict,
) -> tuple[bool, dict, str | None]:
    """Check and transform a call against scope policy.

    Returns (allowed, transformed_params, rejection_reason).
    If allowed is False, rejection_reason explains why.
    If allowed is True, transformed_params has pins applied.
    """
    # 1. DENY check
    if scope.is_denied(group_name, command_name):
        return False, params, f"DENIED: {group_name}.{command_name} is not permitted by scope"

    # Verify the command actually exists in the tool def
    group = next((g for g in tool.groups if g.name == group_name), None)
    if not group:
        return False, params, f"DENIED: group '{group_name}' does not exist"
    cmd = next((c for c in group.commands if c.name == command_name), None)
    if not cmd:
        return False, params, f"DENIED: command '{group_name} {command_name}' does not exist"

    # 2. PIN — override params with fixed values
    pins = scope.get_pins(group_name, command_name)
    enforced_params = dict(params)
    for key, value in pins.items():
        enforced_params[key] = value

    return True, enforced_params, None


def enforce_output(
    scope: ScopeConfig,
    group_name: str,
    command_name: str,
    output: dict,
) -> dict:
    """Strip hidden fields from command output."""
    hidden = scope.get_hidden_outputs(group_name, command_name)
    if not hidden:
        return output
    return {k: v for k, v in output.items() if k not in hidden}


def exec_wrapped(
    tool: ToolDef,
    scope: ScopeConfig,
    group_name: str,
    command_name: str,
    params: dict,
    binary: str | None = None,
) -> tuple[int, str]:
    """Execute a wrapped CLI call with full enforcement.

    1. Check scope (deny / pin)
    2. Build the real CLI command
    3. Run it
    4. Strip hidden fields from output

    Returns (exit_code, output_string).
    """
    # Enforce scope
    allowed, enforced_params, reason = enforce_call(
        scope, tool, group_name, command_name, params,
    )
    if not allowed:
        return 1, json.dumps({"error": reason}, indent=2)

    # Build CLI command
    bin_name = binary or tool.name
    cmd_parts = [bin_name, group_name, command_name]

    # Pass params as --json
    if enforced_params:
        cmd_parts.extend(["--json", json.dumps(enforced_params)])

    # Execute
    result = subprocess.run(
        cmd_parts,
        capture_output=True,
        text=True,
    )

    output_text = result.stdout
    if result.returncode != 0:
        output_text = result.stdout + result.stderr

    # Try to strip hidden fields from JSON output
    hidden = scope.get_hidden_outputs(group_name, command_name)
    if hidden and output_text.strip():
        try:
            output_data = json.loads(output_text)
            output_data = enforce_output(scope, group_name, command_name, output_data)
            output_text = json.dumps(output_data, indent=2)
        except (json.JSONDecodeError, TypeError):
            pass  # not JSON, return as-is

    return result.returncode, output_text
