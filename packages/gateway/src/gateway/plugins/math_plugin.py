"""Simple math plugin — answers basic arithmetic without LLM."""

import re
from gateway.plugins import plugin


@plugin(keywords=["加", "减", "乘", "除", "等于多少", "计算", "算一下", "多少钱"], name="简单计算")
def calculate(text: str) -> str:
    # Extract numbers and operators from text
    # Handles: "3加5", "三加五", "100减20等于多少", "3乘4"
    chinese_ops = {"加": "+", "减": "-", "乘": "*", "除": "/", "乘以": "*", "除以": "/"}
    expr = text
    for cn, op in chinese_ops.items():
        expr = expr.replace(cn, op)

    # Try to find a math expression
    match = re.search(r"(\d+\.?\d*)\s*([+\-*/])\s*(\d+\.?\d*)", expr)
    if not match:
        return None  # Can't parse, fall through to LLM

    a, op, b = float(match.group(1)), match.group(2), float(match.group(3))
    try:
        if op == "+":
            result = a + b
        elif op == "-":
            result = a - b
        elif op == "*":
            result = a * b
        elif op == "/":
            if b == 0:
                return "不能除以零哦"
            result = a / b

        # Format nicely
        if result == int(result):
            return f"等于{int(result)}"
        return f"等于{result:.2f}"
    except Exception:
        return None  # Fall through to LLM
