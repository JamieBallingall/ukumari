"""The arithmetic, one double at a time, as the S evaluator computes it.

There is one error value, carried as NaN. Division by zero (including ``0/0`` and ``x/-0``)
is an error, and so is an infinite result, since the spreadsheet app reports overflow as an
error. ``+``, ``-``, ``*``, ``/`` and negation otherwise propagate errors by IEEE rules
alone. ``minimum`` and ``maximum`` check explicitly, because comparison-based min and max
lose a NaN depending on argument order; on a tie they return the second argument, which
matters only for signed zero. ``power`` is the C library's ``pow``, as ``math.pow`` gives
it, with the cases the app refuses made errors: ``0 ** 0``, zero to a negative power, a
negative number to a fractional power, and a negative number to a power of 4,294,967,295
or more in size (found by having the app compute them, 2026-09-27). The app's own ``^`` is
not correctly rounded: it can differ from ``pow`` in the last few digits, and by more for a
base near 1 raised to a large power, so only the app check's tolerance covers it.

The emitted NumPy program does exactly the same, so the two agree bit for bit.

>>> div(1.0, -0.0), mul(1e308, 10.0), minimum(0.0, -0.0), maximum(float("nan"), 1.0)
(nan, nan, -0.0, nan)
>>> power(2.0, 0.5), power(-8.0, 3.0), power(0.0, 0.0), power(0.0, -1.0)
(1.4142135623730951, -512.0, nan, nan)
>>> power(-8.0, 1 / 3), power(1.0, float("nan")), power(10.0, 400.0), power(-1.0, 2.0**32)
(nan, nan, nan, nan)
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


def power(a: float, b: float) -> float:
    # C's pow gives 1 for 1 ** NaN and NaN ** 0, so errors are checked first.
    if math.isnan(a) or math.isnan(b) or (a == 0.0 and b <= 0.0):
        return math.nan
    if a < 0.0 and abs(b) >= 4294967295.0:
        return math.nan
    try:
        return _finite(math.pow(a, b))
    except ValueError, OverflowError:
        return math.nan


BINARY = {
    Op.ADD: add,
    Op.SUB: sub,
    Op.MUL: mul,
    Op.DIV: div,
    Op.MIN: minimum,
    Op.MAX: maximum,
    Op.POW: power,
}
