"""Discover a CLI tool's interface by traversing its help output.

Strategies (tried in order):
  1. JSON schema — tools that expose structured schemas (e.g. ``gws schema <path>``)
  2. Help-text parsing — standard ``--help`` output (e.g. podman, kubectl, gh)

The result is a YAML file compatible with ``loader.py`` / ``ToolDef``.

Usage::

    from wrapper_crapper.discover import discover_tool, dump_yaml
    tree = discover_tool("podman")
    print(dump_yaml(tree))
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Data model (mirrors tool_def.py but kept separate to avoid coupling)
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredParam:
    name: str
    type: str = "STR"
    description: str = ""
    required: bool = False
    default: str | None = None
    choices: list[str] | None = None
    is_flag: bool = False


@dataclass
class DiscoveredOutput:
    name: str
    type: str = "STR"
    description: str = ""


# ---------------------------------------------------------------------------
# Resource / Object schema
# ---------------------------------------------------------------------------
#
# Many CLIs (especially API wrappers) accept and return structured objects,
# not just flat key=value params.  Think of it as the shape of the JSON blob
# that goes into ``--json '{...}'`` or comes back in stdout.
#
# Real-world examples:
#   - gws drive files create  — requestBody is a File resource (64 fields,
#     nested objects like ``capabilities``, arrays like ``permissions``)
#   - gws gmail users messages get — response is a Message resource with
#     nested ``payload`` (MessagePart), ``labelIds`` (string[]), etc.
#   - kubectl apply -f — the entire YAML/JSON manifest *is* the resource
#   - gh api — raw JSON request/response bodies
#
# The key insight: these are *not* CLI flags.  They are typed, potentially
# nested, potentially recursive structures.  A ``DiscoveredParam`` with
# ``type=STR`` cannot represent "an object with 64 fields, 3 of which are
# themselves objects."
#
# ``SchemaField`` is the recursive building block — analogous to a field in
# a TypeScript interface, a Python dataclass field, or a JSON Schema property:
#
#     interface File {
#         name: string;
#         mimeType: string;
#         capabilities: {          // <-- nested SchemaField, kind="object"
#             canEdit: boolean;
#             canShare: boolean;
#         };
#         parents: string[];       // <-- SchemaField, kind="array", items.kind="string"
#     }
#
# ``SchemaObject`` groups fields into a named type — the resource itself.


@dataclass
class SchemaField:
    """One field inside a resource / structured object.

    Recursive: ``fields`` holds children when ``kind`` is ``"object"``,
    ``items`` describes the element type when ``kind`` is ``"array"``.
    """

    name: str
    kind: str = "string"  # string | integer | boolean | array | object | ref
    description: str = ""
    required: bool = False
    fields: list[SchemaField] = field(default_factory=list)    # kind=object
    items: SchemaField | None = None                           # kind=array
    ref: str | None = None  # unresolved $ref name, e.g. "MessagePart"


@dataclass
class SchemaObject:
    """A named structured type — the 'resource' in REST, 'message' in gRPC,
    'model' in OpenAPI, 'interface' in TypeScript.

    Commands reference these by name for their request body and response body
    instead of (or in addition to) flat params/outputs.
    """

    name: str
    description: str = ""
    fields: list[SchemaField] = field(default_factory=list)


@dataclass
class DiscoveredCommand:
    """A single invocable command.

    Input and output are modeled at two levels that coexist, not compete:

    **Flat (always populated when discoverable):**
      ``params``  — CLI flags, positional args, query parameters.
                    These are what you pass as ``--flag value`` or ``--json '{"key": "val"}'``
                    on the command line.  Most CLIs *only* have these.
      ``outputs`` — named fields in the command's output (when parseable).

    **Structured (populated only when the CLI traffics in JSON objects):**
      ``request_body``  — the shape of the JSON blob the command accepts.
      ``response_body`` — the shape of the JSON blob the command returns.

    A command can have both.  For example, ``gws drive files list`` has:
      - ``params``: pageSize, q, orderBy, ... (URL/query parameters — flat)
      - ``response_body``: FileList { files: File[], nextPageToken: string } (structured)

    A command like ``podman container list`` has only:
      - ``params``: --all, --filter, --format, ... (flat flags)
      - ``request_body`` and ``response_body`` remain None.

    The ``input_style`` hint tells downstream code how this command is
    typically invoked, which matters for rendering and enforcement:
      - ``"flags"``  — standard ``--key value`` flags (podman, git, gh)
      - ``"json"``   — structured JSON via ``--json '{...}'`` (gws, kubectl apply)
      - ``"mixed"``  — both flat flags and a JSON body (gws with URL params + requestBody)
      - ``"positional"`` — unnamed positional args (git checkout <branch>)
    """

    name: str
    description: str = ""
    params: list[DiscoveredParam] = field(default_factory=list)
    outputs: list[DiscoveredOutput] = field(default_factory=list)
    request_body: SchemaObject | None = None
    response_body: SchemaObject | None = None
    input_style: str = "flags"  # flags | json | mixed | positional


# ---------------------------------------------------------------------------
# Recursive group tree
# ---------------------------------------------------------------------------
#
# The current flat model (DiscoveredGroup with a list of commands) works for
# 2-level CLIs like ``podman container list``.  But real tools go deeper:
#
#   podman  machine  os  apply          — 3 levels
#   gws     gmail    users messages get — 4 levels
#   kubectl get      pods -n kube-system — flags, not nesting, but still
#   classroom courses courseWork rubrics create — 5 levels (!)
#
# Flattening into dotted names ("gmail.users.messages") is a lossy hack:
#   - Scope wildcards like ``gmail.*`` don't match ``gmail.users.messages``
#     because is_denied() only checks one level of wildcard.
#   - Rendering a tree from dotted strings requires re-parsing them.
#   - There's no place to hang group-level metadata (description, shared
#     flags) at intermediate levels.
#
# The fix: make ``DiscoveredGroup`` recursive.  A group can contain both
# commands (leaves) and child groups (branches), to arbitrary depth.
#
#   DiscoveredTool
#     └── groups: [DiscoveredGroup]
#           ├── name: "gmail"
#           ├── commands: []          # no direct commands at service level
#           └── children: [DiscoveredGroup]
#                 ├── name: "users"
#                 ├── commands: [getProfile, stop, watch]
#                 └── children: [DiscoveredGroup]
#                       ├── name: "messages"
#                       ├── commands: [get, list, send, delete, ...]
#                       └── children: [DiscoveredGroup]
#                             └── name: "attachments"
#                             └── commands: [get]
#
# This is a straightforward composite pattern.  Traversal, scope matching,
# and rendering all become recursive walks instead of string splitting.
#
# NOTE: This is the *proposed* evolution — not yet wired into the discovery
# functions or the rest of the codebase.  The current flat model and the
# dotted-name convention remain functional.  Migration path:
#   1. Build the recursive tree during discovery (already natural — both
#      _discover_help_recursive and _discover_gws_resource recurse).
#   2. Add a flatten() method that produces the current dotted-name format
#      for backward compat with loader.py / scope.py / render.py.
#   3. Migrate scope.is_denied() to walk the tree with hierarchical wildcards.
#   4. Drop the flatten() shim once all consumers speak tree.


@dataclass
class DiscoveredGroup:
    """A group of commands, optionally containing nested sub-groups.

    ``children`` enables arbitrary nesting depth.  When empty, this is a leaf
    group containing only commands — equivalent to the current flat model.
    """

    name: str
    description: str = ""
    commands: list[DiscoveredCommand] = field(default_factory=list)
    children: list[DiscoveredGroup] = field(default_factory=list)

    # --- Future tree helpers (mock implementations) ---

    def walk(self) -> list[tuple[list[str], DiscoveredCommand]]:
        """Yield (path_segments, command) for every command in the subtree.

        >>> for path, cmd in group.walk():
        ...     print(".".join(path), cmd.name)
        gmail.users.messages  get
        gmail.users.messages  list
        gmail.users.messages.attachments  get
        """
        raise NotImplementedError("TODO: recursive walk")

    def find(self, dotted: str) -> DiscoveredGroup | None:
        """Resolve a dotted path like ``"users.messages.attachments"``
        relative to this group.  Returns None if not found."""
        raise NotImplementedError("TODO: recursive find")

    def flatten(self, prefix: str = "") -> list[DiscoveredGroup]:
        """Collapse the tree into the current flat dotted-name format.

        This is the backward-compat bridge: discovery builds a tree,
        flatten() produces what loader.py / scope.py expect today.
        """
        raise NotImplementedError("TODO: flatten to dotted groups")


@dataclass
class DiscoveredTool:
    name: str
    version: str = "0.1.0"
    description: str = ""
    groups: list[DiscoveredGroup] = field(default_factory=list)
    # Registry of named object schemas discovered across all commands.
    # Keyed by schema name (e.g. "File", "Message", "MessagePart").
    # Commands reference these via request_body / response_body.
    schemas: dict[str, SchemaObject] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract discovery interface
# ---------------------------------------------------------------------------
#
# Each CLI family has its own way of exposing structure.  The ABC below
# defines the contract that a discovery strategy must fulfill.  Concrete
# implementations live in the functions further down (and eventually should
# become proper classes).
#
# The three axes of discovery:
#   1. **Navigation** — how to enumerate subcommands / sub-resources at a
#      given path (``children_of``).
#   2. **Inspection** — how to get the full contract (params, flags, body
#      schema, response schema) for a leaf command (``inspect_command``).
#   3. **Classification** — given raw output from the CLI, decide whether
#      a node is a group (has children) or a leaf (is a command)
#      (``is_group``).
#
# Different strategies implement these differently:
#   - HelpTextDiscovery: runs ``<tool> <path...> --help``, regex-parses.
#   - JsonSchemaDiscovery: runs ``<tool> schema <dotted.path>``, parses JSON.
#   - OpenAPIDiscovery (future): fetches an OpenAPI spec, walks paths.
#   - DiscoveryAPIDiscovery (future): hits Google's Discovery API directly.


class DiscoveryStrategy(ABC):
    """Contract for a CLI discovery strategy."""

    @abstractmethod
    def children_of(self, path: list[str]) -> list[tuple[str, str]]:
        """Return (name, description) pairs for sub-nodes at ``path``.

        An empty list means ``path`` is a leaf (command, not group).
        """
        ...

    @abstractmethod
    def inspect_command(self, path: list[str]) -> DiscoveredCommand:
        """Return the full command definition at ``path``.

        Should extract params/flags, and where available, request/response
        body schemas (as ``SchemaObject``).
        """
        ...

    @abstractmethod
    def is_group(self, path: list[str]) -> bool:
        """Return True if ``path`` has children (is a group, not a command)."""
        ...

    def discover(self, root_path: list[str] | None = None) -> list[DiscoveredGroup]:
        """Generic recursive traversal using the three primitives above.

        Subclasses usually don't need to override this — the default
        implementation walks the tree depth-first using ``children_of``,
        ``is_group``, and ``inspect_command``.
        """
        raise NotImplementedError("TODO: generic recursive walk")


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------

_TIMEOUT = 10  # seconds per invocation


def _run(args: list[str], timeout: int = _TIMEOUT) -> str:
    """Run a command and return combined stdout+stderr."""
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (r.stdout + "\n" + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _run_json(args: list[str], timeout: int = _TIMEOUT) -> dict | None:
    """Run a command, parse stdout as JSON. Return None on failure."""
    import json

    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return json.loads(r.stdout)
    except (
        subprocess.TimeoutExpired,
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
    ):
        return None


# ---------------------------------------------------------------------------
# Help-text parsing
# ---------------------------------------------------------------------------

# Matches lines like:  "  run         Run a command in a new container"
_CMD_RE = re.compile(r"^\s{2,}(\S+)\s{2,}(.+)$")

# Matches option lines like: "  -a, --all   Show all images"
# or: "      --format string   Change the output format"
_FLAG_RE = re.compile(
    r"^\s+"
    r"(?:(-\w),\s+)?"  # short flag  (optional)
    r"(--[\w-]+)"  # long flag   (required)
    r"(?:\s+(\S+))?"  # value hint  (optional: string, int, etc.)
    r"\s{2,}(.+)$"  # description
)

# Matches choice hints like: "(default created)" or "accepts a weight value"
_DEFAULT_RE = re.compile(r"\(default\s+(.+?)\)")
_CHOICE_RE = re.compile(r"\bchoice\b")


def _parse_subcommands(text: str) -> list[tuple[str, str]]:
    """Extract (name, description) pairs from an 'Available Commands' block."""
    results = []
    in_commands = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Available Commands:") or stripped.startswith(
            "Commands:"
        ):
            in_commands = True
            continue
        if in_commands:
            if (
                not stripped
                or stripped.startswith("Options:")
                or stripped.startswith("Flags:")
                or stripped.startswith("FLAGS:")
            ):
                break
            m = _CMD_RE.match(line)
            if m:
                name, desc = m.group(1).strip(), m.group(2).strip()
                # skip help command itself
                if name == "help":
                    continue
                results.append((name, desc))
    return results


def _parse_flags(text: str) -> list[DiscoveredParam]:
    """Extract flags/options from help text."""
    params: list[DiscoveredParam] = []
    in_options = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Options:") or stripped.startswith("Flags:"):
            in_options = True
            continue
        if in_options:
            if not stripped:
                # blank line may end options or just separate groups
                continue
            if stripped.startswith("Available Commands:") or stripped.startswith(
                "Commands:"
            ):
                break
            m = _FLAG_RE.match(line)
            if m:
                short, long_name, value_hint, desc = m.groups()
                flag_name = long_name.lstrip("-")

                is_flag = value_hint is None
                param_type = "STR"
                if value_hint:
                    hint_lower = value_hint.lower()
                    if hint_lower in ("int", "uint", "int32", "int64"):
                        param_type = "INT"
                    elif hint_lower in ("bool", "boolean"):
                        param_type = "BOOL"
                    elif (
                        "array" in hint_lower
                        or "strings" in hint_lower
                        or "stringarray" in hint_lower
                    ):
                        param_type = "LIST"

                default = None
                dm = _DEFAULT_RE.search(desc)
                if dm:
                    default = dm.group(1)

                params.append(
                    DiscoveredParam(
                        name=flag_name,
                        type=param_type,
                        description=desc.strip(),
                        required=False,
                        default=default,
                        is_flag=is_flag,
                    )
                )
    return params


def _parse_description(text: str) -> str:
    """Extract the top-level description from help text."""
    lines = text.splitlines()
    # Many CLIs put description on the first non-empty line, or after "Description:"
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Description:"):
            # next non-empty line
            for j in range(i + 1, min(i + 5, len(lines))):
                desc = lines[j].strip()
                if desc:
                    return desc
            break
    # Fallback: first non-empty line that's not a "Usage:" line
    for line in lines:
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("Usage:")
            and not stripped.startswith("Aliases:")
        ):
            return stripped
    return ""


def _has_subcommands(text: str) -> bool:
    """Check if help text indicates further subcommands."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Available Commands:") or stripped.startswith(
            "Commands:"
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# GWS-style JSON schema strategy
# ---------------------------------------------------------------------------


def _try_gws_schema(tool: str, schema_path: str) -> DiscoveredCommand | None:
    """Try to get a structured schema via ``<tool> schema <dotted.path>``."""
    data = _run_json([tool, "schema", schema_path])
    if not data or "parameters" not in data:
        return None

    params = []
    for pname, pdef in data.get("parameters", {}).items():
        ptype = pdef.get("type", "string").lower()
        if ptype in ("integer", "int32", "int64"):
            mapped = "INT"
        elif ptype == "boolean":
            mapped = "BOOL"
        elif ptype == "array":
            mapped = "LIST"
        else:
            mapped = "STR"

        choices = pdef.get("enum")
        params.append(
            DiscoveredParam(
                name=pname,
                type=mapped,
                description=pdef.get("description", ""),
                required=pdef.get("required", False),
                default=pdef.get("default"),
                choices=choices,
                is_flag=(ptype == "boolean" and not pdef.get("required", False)),
            )
        )

    outputs = []
    response = data.get("response")
    if isinstance(response, dict):
        resp_props = response.get("properties") or response.get("schema", {}).get(
            "properties"
        )
        if isinstance(resp_props, dict):
            for oname, odef in resp_props.items():
                otype = odef.get("type", "string").lower()
                if otype in ("integer", "int32", "int64", "number"):
                    mapped_o = "INT"
                elif otype == "boolean":
                    mapped_o = "BOOL"
                elif otype == "array":
                    mapped_o = "LIST"
                else:
                    mapped_o = "STR"
                outputs.append(
                    DiscoveredOutput(
                        name=oname,
                        type=mapped_o,
                        description=odef.get("description", ""),
                    )
                )

    method = schema_path.rsplit(".", 1)[-1]
    return DiscoveredCommand(
        name=method,
        description=data.get("description", ""),
        params=params,
        outputs=outputs,
    )


# Same here. For Google, it actually makes much more sense to use their Discovery API
def _discover_gws_resource(
    tool: str,
    cli_path: list[str],
    dotted_prefix: str,
) -> list[DiscoveredGroup]:
    """Recursively discover a gws resource that may contain sub-resources.

    ``cli_path`` is the list of CLI args to reach this level (e.g. ["gmail", "users", "messages"]).
    ``dotted_prefix`` is the dotted group name so far (e.g. "gmail.users.messages").
    """
    help_text = _run([tool] + cli_path)
    entries = _parse_subcommands(help_text)
    if not entries:
        return []

    groups: list[DiscoveredGroup] = []
    group = DiscoveredGroup(
        name=dotted_prefix, description=f"Operations on the '{cli_path[-1]}' resource"
    )
    commands_in_group: list[DiscoveredCommand] = []

    for entry_name, entry_desc in entries:
        schema_path = f"{dotted_prefix}.{entry_name}"
        cmd = _try_gws_schema(tool, schema_path)
        if cmd:
            commands_in_group.append(cmd)
        else:
            # Might be a sub-resource — check if it has its own methods
            sub_help = _run([tool] + cli_path + [entry_name])
            sub_entries = _parse_subcommands(sub_help)
            if sub_entries:
                # It's a sub-resource, recurse
                sub_groups = _discover_gws_resource(
                    tool,
                    cli_path + [entry_name],
                    schema_path,
                )
                groups.extend(sub_groups)
            else:
                # Leaf with no schema — add as bare command
                commands_in_group.append(
                    DiscoveredCommand(
                        name=entry_name,
                        description=entry_desc,
                    )
                )

    if commands_in_group:
        group.commands = commands_in_group
        groups.insert(0, group)

    return groups


# BUG: This is just perfect example of the vibecoded crap
def _discover_gws(tool: str) -> DiscoveredTool | None:
    """Discover a gws-style tool that has ``schema`` and structured JSON output."""
    top_help = _run([tool, "--help"])
    if "schema" not in top_help.lower():
        return None

    # Parse services from "SERVICES:" section
    services: list[tuple[str, str]] = []
    in_services = False
    for line in top_help.splitlines():
        stripped = line.strip()
        if stripped.startswith("SERVICES:"):
            in_services = True
            continue
        if in_services:
            if (
                not stripped
                or stripped.startswith("ENVIRONMENT:")
                or stripped.startswith("EXIT")
                or stripped.startswith("FLAGS:")
            ):
                break
            m = _CMD_RE.match(line)
            if m:
                services.append((m.group(1).strip(), m.group(2).strip()))

    if not services:
        return None

    desc_line = ""
    for line in top_help.splitlines():
        stripped = line.strip()
        if stripped and "—" in stripped:
            desc_line = stripped
            break

    discovered = DiscoveredTool(name=tool, description=desc_line)

    for svc_name, svc_desc in services:
        svc_help = _run([tool, svc_name])
        resources = _parse_subcommands(svc_help)
        if not resources:
            continue

        for res_name, res_desc in resources:
            res_groups = _discover_gws_resource(
                tool,
                [svc_name, res_name],
                f"{svc_name}.{res_name}",
            )
            groups_with_desc = []
            for g in res_groups:
                if g.name == f"{svc_name}.{res_name}" and not g.description.strip():
                    g.description = res_desc
                groups_with_desc.append(g)
            discovered.groups.extend(groups_with_desc)

    return discovered if discovered.groups else None


# ---------------------------------------------------------------------------
# Generic --help traversal strategy
# ---------------------------------------------------------------------------


def _discover_help_recursive(
    tool: str,
    prefix: list[str],
    max_depth: int = 3,
    depth: int = 0,
) -> list[DiscoveredGroup]:
    """Recursively traverse ``--help`` to build groups and commands."""
    if depth > max_depth:
        return []

    help_text = _run([tool] + prefix + ["--help"])
    if not help_text:
        return []

    subs = _parse_subcommands(help_text)
    if not subs:
        return []

    groups: list[DiscoveredGroup] = []

    for sub_name, sub_desc in subs:
        sub_help = _run([tool] + prefix + [sub_name, "--help"])
        if not sub_help:
            continue

        if _has_subcommands(sub_help):
            # This is an intermediate node — recurse
            child_subs = _parse_subcommands(sub_help)
            commands = []
            nested_groups: list[DiscoveredGroup] = []

            for child_name, child_desc in child_subs:
                child_help = _run([tool] + prefix + [sub_name, child_name, "--help"])
                if child_help and _has_subcommands(child_help):
                    # Deeper nesting — recurse further
                    deeper = _discover_help_recursive(
                        tool,
                        prefix + [sub_name, child_name],
                        max_depth=max_depth,
                        depth=depth + 2,
                    )
                    nested_groups.extend(deeper)
                else:
                    # Leaf command
                    params = _parse_flags(child_help) if child_help else []
                    commands.append(
                        DiscoveredCommand(
                            name=child_name,
                            description=child_desc,
                            params=params,
                        )
                    )

            if commands:
                groups.append(
                    DiscoveredGroup(
                        name=".".join(prefix + [sub_name]) if prefix else sub_name,
                        description=sub_desc,
                        commands=commands,
                    )
                )
            groups.extend(nested_groups)
        else:
            # Leaf command at this level — add to a catch-all group
            params = _parse_flags(sub_help)
            # Find or create a group for the current prefix
            group_name = ".".join(prefix) if prefix else tool
            existing = next((g for g in groups if g.name == group_name), None)
            if not existing:
                existing = DiscoveredGroup(name=group_name, description="")
                groups.append(existing)
            existing.commands.append(
                DiscoveredCommand(
                    name=sub_name,
                    description=sub_desc,
                    params=params,
                )
            )

    return groups


def _discover_help(tool: str) -> DiscoveredTool:
    """Discover a tool by recursively parsing ``--help`` output."""
    top_help = _run([tool, "--help"])
    desc = _parse_description(top_help)

    # Try to get version
    version = "0.1.0"
    ver_text = _run([tool, "--version"])
    ver_match = re.search(r"(\d+\.\d+\.\d+)", ver_text)
    if ver_match:
        version = ver_match.group(1)

    # Also collect top-level flags
    top_params = _parse_flags(top_help)

    groups = _discover_help_recursive(tool, [])

    # If there are top-level leaf commands (not under a subcommand group),
    # they end up in a group named after the tool — rename to "_root"
    for g in groups:
        if g.name == tool:
            g.name = "_root"
            g.description = "Top-level commands"

    # Attach top-level flags as a synthetic _global group if non-empty
    if top_params:
        global_group = DiscoveredGroup(
            name="_global",
            description="Global flags available on all commands",
            commands=[
                DiscoveredCommand(
                    name="_flags",
                    description="Global flags",
                    params=top_params,
                )
            ],
        )
        groups.insert(0, global_group)

    return DiscoveredTool(
        name=tool,
        version=version,
        description=desc,
        groups=groups,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_tool(tool: str) -> DiscoveredTool:
    """Auto-discover a CLI tool's full interface.

    Tries JSON-schema strategy first (gws-style), falls back to --help parsing.
    """
    # Strategy 1: structured schema (gws-style)
    result = _discover_gws(tool)
    if result:
        return result

    # Strategy 2: generic --help traversal
    return _discover_help(tool)


def _param_to_dict(p: DiscoveredParam) -> dict[str, Any]:
    d: dict[str, Any] = {"name": p.name, "type": p.type}
    if p.description:
        d["description"] = p.description
    if p.required:
        d["required"] = True
    if p.default is not None:
        d["default"] = p.default
    if p.choices:
        d["choices"] = p.choices
    if p.is_flag:
        d["is_flag"] = True
    return d


def _output_to_dict(o: DiscoveredOutput) -> dict[str, Any]:
    d: dict[str, Any] = {"name": o.name, "type": o.type}
    if o.description:
        d["description"] = o.description
    return d


def to_dict(tool: DiscoveredTool) -> dict[str, Any]:
    """Convert a DiscoveredTool to a dict matching the ToolDef YAML format."""
    groups = []
    for g in tool.groups:
        commands = []
        for c in g.commands:
            cmd: dict[str, Any] = {"name": c.name}
            if c.description:
                cmd["description"] = c.description
            if c.params:
                cmd["params"] = [_param_to_dict(p) for p in c.params]
            if c.outputs:
                cmd["outputs"] = [_output_to_dict(o) for o in c.outputs]
            commands.append(cmd)
        group: dict[str, Any] = {"name": g.name}
        if g.description:
            group["description"] = g.description
        group["commands"] = commands
        groups.append(group)

    return {
        "name": tool.name,
        "version": tool.version,
        "description": tool.description,
        "groups": groups,
    }


def dump_yaml(tool: DiscoveredTool) -> str:
    """Serialize a DiscoveredTool to YAML (compatible with ``loader.py``)."""
    return yaml.dump(
        to_dict(tool),
        default_flow_style=False,
        sort_keys=False,
        width=120,
        allow_unicode=True,
    )


# ---------------------------------------------------------------------------
# CLI entry point (standalone usage)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            f"usage: python -m wrapper_crapper.discover <tool> [--output <file>]",
            file=sys.stderr,
        )
        sys.exit(1)

    tool_name = sys.argv[1]
    output_file = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]

    print(f"Discovering {tool_name}...", file=sys.stderr)
    discovered = discover_tool(tool_name)
    result = dump_yaml(discovered)

    if output_file:
        from pathlib import Path

        Path(output_file).write_text(result)
        print(f"Wrote {output_file}", file=sys.stderr)
    else:
        print(result)
