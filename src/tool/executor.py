from typing import Any

from .registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:

        tool = self.registry.get(name)

        if tool is None:
            raise ValueError(f"Tool not found: {name}")

        return tool.handler(**arguments)