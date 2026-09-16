from .model import Tool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._version = 0

    def register(self, tool: Tool):
        self._tools[tool.spec.name] = tool
        self._version += 1

    def unregister(self, name: str):
        if name in self._tools:
            del self._tools[name]
            self._version += 1

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        return [
            {
                "name": tool.spec.name,
                "description": tool.spec.description,
                "parameters": tool.spec.parameters,
            }
            for tool in self._tools.values()
        ]

    @property
    def version(self) -> int:
        return self._version