"""The S evaluator: one forward pass over S, one double at a time.

It exists to check the emitted program, not to compute values normally: two independent
computations that must agree bit for bit.
"""

import math
from collections.abc import Mapping, Sequence

from ukumari.arith import BINARY, neg
from ukumari.expr import Op
from ukumari.unroll import Const, Element, Operation, Prim, Straight


def evaluate(s: Straight, inputs: Mapping[str, Sequence[float]]) -> list[float]:
    """Every node's value, in node order. An infinite input is the error value."""
    values: list[float] = []
    for node in s.nodes:
        match node:
            case Const(value):
                values.append(value)
            case Element(name, index):
                x = float(inputs[name][index])
                values.append(math.nan if math.isinf(x) else x)
            case Operation(Prim.NEG, (a,)):
                values.append(neg(values[a]))
            case Operation(prim, (a, b)):
                values.append(BINARY[Op(prim.value)](values[a], values[b]))
            case Operation():
                raise AssertionError(f"a malformed node: {node}")
    return values


def cell_values(
    s: Straight, inputs: Mapping[str, Sequence[float]]
) -> dict[tuple[str, int | None], float]:
    """Every cell's value, keyed by (name, position)."""
    values = evaluate(s, inputs)
    return {cell: values[node] for cell, node in s.cells.items()}
