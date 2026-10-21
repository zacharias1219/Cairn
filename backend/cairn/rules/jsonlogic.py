"""A deterministic JSON-logic evaluator.

Rules are data: ``{"op": [args...]}``. Evaluation is pure: no clock, no
randomness, no I/O and no model on the path, so the same input always gives
the same result (F4).
"""

from __future__ import annotations

import re
from typing import Any, Callable

_MISSING = object()


class RuleSyntaxError(ValueError):
    pass


def _get_var(data: Any, path: Any, default: Any = None) -> Any:
    if path in (None, ""):
        return data
    cur = data
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur


def _truthy(v: Any) -> bool:
    if isinstance(v, list):
        return len(v) > 0
    return bool(v)


def _num(v: Any) -> float:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _cmp(op: Callable[[float, float], bool]):
    def f(*args):
        if len(args) == 3:  # between: a < b < c
            return op(_num(args[0]), _num(args[1])) and op(_num(args[1]), _num(args[2]))
        a, b = args[0], args[1]
        if isinstance(a, str) and isinstance(b, str):
            return op(a, b)
        return op(_num(a), _num(b))
    return f


def _loose_eq(a, b):
    if isinstance(a, (int, float)) and isinstance(b, str) or isinstance(b, (int, float)) and isinstance(a, str):
        return _num(a) == _num(b)
    return a == b


def _lower(v: Any) -> str:
    return str(v or "").lower()


OPS: dict[str, Callable[..., Any]] = {
    "==": _loose_eq,
    "===": lambda a, b: a == b,
    "!=": lambda a, b: not _loose_eq(a, b),
    "!==": lambda a, b: a != b,
    ">": _cmp(lambda a, b: a > b),
    ">=": _cmp(lambda a, b: a >= b),
    "<": _cmp(lambda a, b: a < b),
    "<=": _cmp(lambda a, b: a <= b),
    "!": lambda a: not _truthy(a),
    "!!": lambda a: _truthy(a),
    "+": lambda *a: sum(_num(x) for x in a),
    "-": lambda a, b=None: -_num(a) if b is None else _num(a) - _num(b),
    "*": lambda *a: __import__("math").prod(_num(x) for x in a),
    "/": lambda a, b: _num(a) / _num(b) if _num(b) else float("nan"),
    "%": lambda a, b: _num(a) % _num(b) if _num(b) else float("nan"),
    "min": lambda *a: min(_num(x) for x in a),
    "max": lambda *a: max(_num(x) for x in a),
    "in": lambda a, b: (a in b) if isinstance(b, (list, str)) else False,
    "cat": lambda *a: "".join(str(x) for x in a),
    "lower": lambda a: _lower(a),
    # Cairn extensions, still pure functions of their input.
    "contains_any": lambda text, words: any(_lower(w) in _lower(text) for w in (words or [])),
    "matches": lambda text, pattern: bool(re.search(pattern, str(text or ""), re.I)),
    "length": lambda a: len(a) if isinstance(a, (list, str)) else 0,
}

LAZY = {"if", "?:", "and", "or", "var", "missing", "missing_some", "all", "some", "none"}


def apply(logic: Any, data: Any = None) -> Any:
    if isinstance(logic, list):
        return [apply(x, data) for x in logic]
    if not isinstance(logic, dict) or len(logic) != 1:
        return logic
    op, raw = next(iter(logic.items()))
    args = raw if isinstance(raw, list) else [raw]

    if op == "var":
        path = apply(args[0], data) if args else None
        default = apply(args[1], data) if len(args) > 1 else None
        return _get_var(data, path, default)
    if op == "missing":
        keys = args[0] if len(args) == 1 and isinstance(args[0], list) else args
        return [k for k in (apply(k, data) for k in keys) if _get_var(data, k, _MISSING) in (_MISSING, None, "")]
    if op == "missing_some":
        need, keys = apply(args[0], data), apply(args[1], data)
        missing = [k for k in keys if _get_var(data, k, _MISSING) in (_MISSING, None, "")]
        return [] if len(keys) - len(missing) >= need else missing
    if op in ("if", "?:"):
        i = 0
        while i < len(args) - 1:
            if _truthy(apply(args[i], data)):
                return apply(args[i + 1], data)
            i += 2
        return apply(args[i], data) if i < len(args) else None
    if op == "and":
        v = True
        for a in args:
            v = apply(a, data)
            if not _truthy(v):
                return v
        return v
    if op == "or":
        v = False
        for a in args:
            v = apply(a, data)
            if _truthy(v):
                return v
        return v
    if op in ("all", "some", "none"):
        items = apply(args[0], data) or []
        results = [_truthy(apply(args[1], item)) for item in items]
        if op == "all":
            return bool(items) and all(results)
        if op == "some":
            return any(results)
        return not any(results)

    fn = OPS.get(op)
    if fn is None:
        raise RuleSyntaxError(f"unknown operator: {op}")
    return fn(*[apply(a, data) for a in args])


def validate(logic: Any) -> None:
    """Raise RuleSyntaxError for unknown operators anywhere in the tree."""
    if isinstance(logic, list):
        for x in logic:
            validate(x)
        return
    if isinstance(logic, dict):
        if len(logic) != 1:
            raise RuleSyntaxError("each operation must have exactly one operator")
        op, raw = next(iter(logic.items()))
        if op not in OPS and op not in LAZY:
            raise RuleSyntaxError(f"unknown operator: {op}")
        validate(raw)


def variables(logic: Any) -> list[str]:
    """Every var path a rule reads, for the console's rule explainer."""
    out: list[str] = []
    if isinstance(logic, list):
        for x in logic:
            out += variables(x)
    elif isinstance(logic, dict):
        for op, raw in logic.items():
            if op == "var":
                p = raw[0] if isinstance(raw, list) else raw
                if isinstance(p, str):
                    out.append(p)
            else:
                out += variables(raw)
    return sorted(set(out))
