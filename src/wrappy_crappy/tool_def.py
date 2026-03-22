"""Tool definition format.

A wrapped tool is described as a YAML file with groups, commands,
parameters (with types/defaults/required), and output fields.
This is the canonical internal representation — parsed from whatever
the original CLI exposes (--help, JSON schema, OpenAPI, etc).
"""

from dataclasses import dataclass, field


@dataclass
class Param:
    name: str
    type: str = "STR"
    description: str = ""
    required: bool = False
    default: str | None = None
    choices: list[str] | None = None
    is_flag: bool = False


@dataclass
class OutputField:
    name: str
    type: str = "STR"
    description: str = ""


@dataclass
class Command:
    name: str
    description: str = ""
    params: list[Param] = field(default_factory=list)
    outputs: list[OutputField] = field(default_factory=list)


@dataclass
class Group:
    name: str
    description: str = ""
    commands: list[Command] = field(default_factory=list)


@dataclass
class ToolDef:
    name: str
    version: str = "0.1.0"
    description: str = ""
    groups: list[Group] = field(default_factory=list)
