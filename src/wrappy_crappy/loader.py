"""Load a tool definition from YAML."""

from pathlib import Path

import yaml

from wrappy_crappy.tool_def import Command, Group, OutputField, Param, ToolDef


def load_tool(path: Path) -> ToolDef:
    data = yaml.safe_load(path.read_text())
    groups = []
    for g in data.get("groups", []):
        commands = []
        for c in g.get("commands", []):
            params = [
                Param(
                    name=p["name"],
                    type=p.get("type", "STR"),
                    description=p.get("description", ""),
                    required=p.get("required", False),
                    default=p.get("default"),
                    choices=p.get("choices"),
                    is_flag=p.get("is_flag", False),
                )
                for p in c.get("params", [])
            ]
            outputs = [
                OutputField(
                    name=o["name"],
                    type=o.get("type", "STR"),
                    description=o.get("description", ""),
                )
                for o in c.get("outputs", [])
            ]
            commands.append(Command(
                name=c["name"],
                description=c.get("description", ""),
                params=params,
                outputs=outputs,
            ))
        groups.append(Group(
            name=g["name"],
            description=g.get("description", ""),
            commands=commands,
        ))
    return ToolDef(
        name=data["name"],
        version=data.get("version", "0.1.0"),
        description=data.get("description", ""),
        groups=groups,
    )
