"""Scope-aware renderers.

Discovery strategy:
  - Root level: tree only (groups + command names, cheap overview)
  - Group/command level: TypeScript interfaces (precise contracts)

The scope filters what's visible. Denied commands vanish.
Pinned params show as fixed values. Hidden output fields disappear.
The agent never learns what it can't use.
"""

from wrapper_crapper.tool_def import Command, Group, Param, ToolDef
from wrapper_crapper.scope import ScopeConfig


# ---------------------------------------------------------------------------
# Scope filtering
# ---------------------------------------------------------------------------


def apply_scope(tool: ToolDef, scope: ScopeConfig) -> ToolDef:
    """Return a new ToolDef with scope applied — denied commands removed,
    pinned params fixed, hidden outputs stripped."""
    filtered_groups = []
    for group in tool.groups:
        filtered_cmds = []
        for cmd in group.commands:
            if scope.is_denied(group.name, cmd.name):
                continue

            pins = scope.get_pins(group.name, cmd.name)
            hidden = scope.get_hidden_outputs(group.name, cmd.name)

            new_params = []
            for p in cmd.params:
                if p.name in pins:
                    new_params.append(
                        Param(
                            name=p.name,
                            type=p.type,
                            description=f"FIXED: {pins[p.name]}",
                            required=False,
                            default=pins[p.name],
                            choices=None,
                            is_flag=p.is_flag,
                        )
                    )
                else:
                    new_params.append(p)

            new_outputs = [o for o in cmd.outputs if o.name not in hidden]

            filtered_cmds.append(
                Command(
                    name=cmd.name,
                    description=cmd.description,
                    params=new_params,
                    outputs=new_outputs,
                )
            )

        if filtered_cmds:
            filtered_groups.append(
                Group(
                    name=group.name,
                    description=group.description,
                    commands=filtered_cmds,
                )
            )

    return ToolDef(
        name=tool.name,
        version=tool.version,
        description=tool.description,
        groups=filtered_groups,
    )


# ---------------------------------------------------------------------------
# Tree renderer — root level only
# ---------------------------------------------------------------------------


# FIXME: This is super fragile
def render_tree_root(tool: ToolDef, scope: ScopeConfig | None = None) -> str:
    if scope:
        tool = apply_scope(tool, scope)
    lines = [f"{tool.name} v{tool.version} — {tool.description}\n"]
    lines.append(f"{tool.name}/")
    for idx, group in enumerate(tool.groups):
        is_last = idx == len(tool.groups) - 1
        prefix = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "
        lines.append(f"{prefix}{group.name + '/':24s}{group.description}")
        for sub_idx, cmd in enumerate(group.commands):
            sub_last = sub_idx == len(group.commands) - 1
            sub_prefix = "└── " if sub_last else "├── "
            lines.append(f"{child_prefix}{sub_prefix}{cmd.name}")
    lines.append("")
    lines.append(f"Use: wc schema <tool> <group> for TypeScript interfaces")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TypeScript renderer — group and command level
# ---------------------------------------------------------------------------


# REFACTOR: It belongs to a class. TypeScriptInterface (renderer)
def _ts_type(param: Param) -> str:
    if param.is_flag:
        return "boolean"
    if param.choices:
        return " | ".join(f'"{c}"' for c in param.choices)
    t = param.type.upper()
    if t in ("INT", "NUMBER"):
        return "number"
    if t == "BOOL":
        return "boolean"
    if t in ("LIST", "ARRAY"):
        return "string[]"
    return "string"


# REFACTOR: It belongs to a class. TypeScriptInterface (renderer)
def _ts_out_type(type_str: str) -> str:
    t = type_str.upper()
    if t in ("INT", "NUMBER"):
        return "number"
    if t == "BOOL":
        return "boolean"
    if t in ("LIST", "ARRAY"):
        return "any[]"
    return "string"


# REFACTOR: It belongs to a class. TypeScriptInterface (renderer)
def render_ts_group(
    tool: ToolDef, group_name: str, scope: ScopeConfig | None = None
) -> str:
    if scope:
        tool = apply_scope(tool, scope)
    group = next((g for g in tool.groups if g.name == group_name), None)
    if not group:
        return f"// Group '{group_name}' not found (may be denied by scope)"

    lines = [f"// {tool.name} {group.name} — {group.description}\n"]
    for cmd in group.commands:
        lines.append(_render_ts_command_block(tool.name, group.name, cmd))
        lines.append("")
    return "\n".join(lines)


# REFACTOR: It belongs to a class. TypeScriptInterface (renderer)
def render_ts_command(
    tool: ToolDef, group_name: str, cmd_name: str, scope: ScopeConfig | None = None
) -> str:
    if scope:
        tool = apply_scope(tool, scope)
    group = next((g for g in tool.groups if g.name == group_name), None)
    if not group:
        return f"// Group '{group_name}' not found (may be denied by scope)"
    cmd = next((c for c in group.commands if c.name == cmd_name), None)
    if not cmd:
        return (
            f"// Command '{group_name} {cmd_name}' not found (may be denied by scope)"
        )
    return _render_ts_command_block(tool.name, group.name, cmd)


# REFACTOR: It belongs to a class. TypeScriptInterface (renderer)
def _render_ts_command_block(tool_name: str, group_name: str, cmd: Command) -> str:
    pascal = cmd.name.replace("-", " ").title().replace(" ", "")
    lines = [f"// {tool_name} {group_name} {cmd.name} — {cmd.description}"]

    if cmd.params:
        lines.append(f"interface {pascal}Input {{")
        for p in cmd.params:
            ts = _ts_type(p)
            opt = "?" if not p.required else ""
            comment = ""
            if p.description:
                comment = f"  // {p.description}"
            lines.append(f"  {p.name}{opt}: {ts};{comment}")
        lines.append("}")

    if cmd.outputs:
        lines.append(f"interface {pascal}Output {{")
        for o in cmd.outputs:
            ts = _ts_out_type(o.type)
            comment = f"  // {o.description}" if o.description else ""
            lines.append(f"  {o.name}: {ts};{comment}")
        lines.append("}")

    return "\n".join(lines)
