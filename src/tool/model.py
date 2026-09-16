from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Tool:
    spec: ToolSpec
    handler: Callable[..., Any]