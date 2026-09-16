from .model import Tool, ToolSpec


def echo(text: str):
    return text


def add(a: int, b: int):
    return a + b


ECHO_TOOL = Tool(
    spec=ToolSpec(
        name="echo",
        description="입력받은 문자열을 그대로 반환합니다.",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                }
            },
            "required": ["text"],
        },
    ),
    handler=echo,
)


ADD_TOOL = Tool(
    spec=ToolSpec(
        name="add",
        description="두 숫자를 더합니다.",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    ),
    handler=add,
)