"""The arithmetic, one double at a time, as the S evaluator computes it.

There is one error value, carried as NaN. Division by zero (including ``0/0`` and ``x/-0``)
is an error, and so is an infinite result, since the spreadsheet app reports overflow as an
error. ``+``, ``-``, ``*``, ``/`` and negation otherwise propagate errors by IEEE rules
alone. ``minimum`` and ``maximum`` check explicitly, because comparison-based min and max
lose a NaN depending on argument order; on a tie they return the second argument, which
matters only for signed zero.

The emitted NumPy program does exactly the same, so the two agree bit for bit.

>>> div(1.0, -0.0), mul(1e308, 10.0), minimum(0.0, -0.0), maximum(float("nan"), 1.0)
(nan, nan, -0.0, nan)
"""

import math

from ukumari.expr import Op


def _finite(x: float) -> float:
    return math.nan if math.isinf(x) else x


def add(a: float, b: float) -> float:
    return _finite(a + b)


def sub(a: float, b: float) -> float:
    return _finite(a - b)


def mul(a: float, b: float) -> float:
    return _finite(a * b)


def div(a: float, b: float) -> float:
    if b == 0.0:
        return math.nan
    return _finite(a / b)


def neg(a: float) -> float:
    return -a


def minimum(a: float, b: float) -> float:
    if math.isnan(a) or math.isnan(b):
        return math.nan
    return min(b, a)  # a when a < b, else b: on a tie, the second argument


def maximum(a: float, b: float) -> float:
    if math.isnan(a) or math.isnan(b):
        return math.nan
    return max(b, a)  # a when a > b, else b: on a tie, the second argument


BINARY = {
    Op.ADD: add,
    Op.SUB: sub,
    Op.MUL: mul,
    Op.DIV: div,
    Op.MIN: minimum,
    Op.MAX: maximum,
}
