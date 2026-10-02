
from copy import deepcopy

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_laptops",
            "description": "사용 가능한 노트북 후보를 검색한다.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
]

TOOL_FUNCTIONS = {}

LAPTOPS = [
    {
        "name": "Alpha Lite",
        "price": 1_250_000,
        "ram_gb": 16,
        "gpu": "Integrated",
        "weight_kg": 1.1,
    },
    {
        "name": "Beta RTX",
        "price": 1_450_000,
        "ram_gb": 16,
        "gpu": "NVIDIA RTX 4050",
        "weight_kg": 1.8,
    },
    {
        "name": "Gamma Creator",
        "price": 1_490_000,
        "ram_gb": 32,
        "gpu": "NVIDIA RTX 4060",
        "weight_kg": 2.2,
    },
    {
        "name": "Delta Pro",
        "price": 1_350_000,
        "ram_gb": 32,
        "gpu": "Integrated",
        "weight_kg": 1.5,
    },
]

def search_laptops():
    return deepcopy(LAPTOPS)

TOOL_FUNCTIONS = {
    "search_laptops": search_laptops,
}

def execute_tool(name, args):

    if name not in TOOL_FUNCTIONS:
        raise ValueError(f"Unknown tool: {name}")

    function = TOOL_FUNCTIONS[name]

    return function(**args)