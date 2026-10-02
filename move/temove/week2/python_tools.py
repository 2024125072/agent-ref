import ast
import operator


# ---------------------------------------------------------------------------
# Tool 스키마: LLM에게 노출되는 도구 명세
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_price",
            "description":
                "상품 이름으로 가격을 조회한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {
                        "type": "string",
                        "description":
                            "가격을 조회할 상품 이름"
                    }
                },
                "required": ["product"],
                "additionalProperties": False,
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description":
                "숫자 산술식을 계산한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description":
                            "계산할 산술식"
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool 구현
# ---------------------------------------------------------------------------

CATALOG = {
    "노트북 A": 1_250_000,
    "모니터 B": 320_000,
    "키보드 C": 89_000,
}

def get_price(product: str):
    # 없는 상품이면 크래시 대신 복구 힌트를 반환한다.
    # 모델은 available_products를 보고 정확한 이름으로 다시 시도할 수 있다.
    if product not in CATALOG:
        return {
            "status": "not_found",
            "product": product,
            "available_products": list(CATALOG),
        }

    return {
        "product": product,
        "price": CATALOG[product],
        "currency": "KRW",
    }


OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)

    if isinstance(node, ast.Constant):
        # 숫자만 허용한다. 문자열 상수를 허용하면 'a' * 10**6 같은
        # 식으로 임의의 메모리를 쓰게 할 수 있다.
        if not isinstance(node.value, (int, float)):
            raise ValueError("Only numeric constants are allowed")
        return node.value

    # 음수 표현(-100, 3 * -2)을 지원한다.
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)

    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        op = OPS[type(node.op)]
        return op(
            _eval(node.left),
            _eval(node.right)
        )

    raise ValueError("Unsupported expression")

def calculator(expression: str):
    # 잘못된 식(SyntaxError)이나 0으로 나누기는 여기서 잡지 않는다.
    # agent loop가 예외를 error 결과로 바꿔 모델에게 되돌린다.
    tree = ast.parse(expression, mode="eval")

    return {
        "expression": expression,
        "result": _eval(tree)
    }


# ---------------------------------------------------------------------------
# Tool 디스패치
# ---------------------------------------------------------------------------

TOOL_FUNCTIONS = {
    "get_price": get_price,
    "calculator": calculator,
}


def execute_tool(name, args):
    # 모든 tool call은 이 함수 하나를 통해 실행된다.
    # week_03에서 (name, args, state)로, week_06에서
    # (name, args, state, step)으로 시그니처가 확장된다.
    if name not in TOOL_FUNCTIONS:
        raise ValueError(f"Unknown tool: {name}")

    function = TOOL_FUNCTIONS[name]

    return function(**args)
