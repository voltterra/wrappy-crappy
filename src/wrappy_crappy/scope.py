"""Scope configuration — deny commands, pin params, hide fields.

Scope YAML format:

    deny:
      - group.command
    pin:
      group.command:
        param_name: fixed_value
    hide_output:
      group.command:
        - field_name
    constraints:
      group:
        key: value
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ScopeConfig:
    deny: list[str] = field(default_factory=list)
    pin: dict[str, dict[str, str]] = field(default_factory=dict)
    hide_output: dict[str, list[str]] = field(default_factory=dict)
    constraints: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "ScopeConfig":
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text()) or {}
        return cls(
            deny=data.get("deny", []),
            pin=data.get("pin", {}),
            hide_output=data.get("hide_output", {}),
            constraints=data.get("constraints", {}),
        )

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if self.deny:
            data["deny"] = self.deny
        if self.pin:
            data["pin"] = self.pin
        if self.hide_output:
            data["hide_output"] = self.hide_output
        if self.constraints:
            data["constraints"] = self.constraints
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))

    def is_denied(self, group: str, command: str) -> bool:
        key = f"{group}.{command}"
        return key in self.deny or f"{group}.*" in self.deny

    def get_pins(self, group: str, command: str) -> dict[str, str]:
        return self.pin.get(f"{group}.{command}", {})

    def get_hidden_outputs(self, group: str, command: str) -> list[str]:
        return self.hide_output.get(f"{group}.{command}", [])

    def get_constraint(self, group: str, key: str) -> str | None:
        return self.constraints.get(group, {}).get(key)
