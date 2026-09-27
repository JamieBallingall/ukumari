"""P against the S evaluator, bit for bit.

Two independent computations of the same model must agree exactly: every bit of every
double, so ``0.0`` and ``-0.0`` differ, while any NaN is the one error value. A
disagreement is a bug in ukumari, so it raises ``AssertionError``.
"""

import math
import struct
from collections.abc import Mapping

import numpy as np

from ukumari.bind import Bound
from ukumari.circuit import Kind
from ukumari.unroll import Cell


def same(a: float, b: float) -> bool:
    """Whether two doubles are identical, any NaN being the same error value.

    >>> same(0.1 + 0.2, 0.30000000000000004), same(0.0, -0.0), same(math.nan, -math.nan)
    (True, False, True)
    """
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return struct.pack("<d", a) == struct.pack("<d", b)


def program_cells(
    bound: Bound, outputs: Mapping[str, np.ndarray], scenario: int = 0
) -> dict[Cell, float]:
    """Every computed cell's value in one scenario of P's outputs."""
    cells: dict[Cell, float] = {}
    for d in bound.circuit.declarations:
        if d.kind is not Kind.VECTOR:
            continue
        row = outputs[d.name][scenario]
        interval = bound.intervals[d.name]
        if interval is None:
            cells[(d.name, None)] = float(row[0])
        else:
            for column, t in enumerate(range(interval.start, interval.stop)):
                cells[(d.name, t)] = float(row[column])
    return cells


def check_agreement(
    program: Mapping[Cell, float], evaluator: Mapping[Cell, float]
) -> None:
    """Raise ``AssertionError`` unless every cell P computed equals the evaluator's."""
    wrong = [
        f"{name!r}[{position}]: P gives {program[(name, position)]!r}, "
        f"S gives {evaluator[(name, position)]!r}"
        for name, position in program
        if not same(program[(name, position)], evaluator[(name, position)])
    ]
    if wrong:
        shown = "\n".join(wrong[:10])
        more = f"\n… and {len(wrong) - 10} more" if len(wrong) > 10 else ""
        raise AssertionError(
            f"P and the S evaluator disagree in {len(wrong)} cell(s), a bug in "
            f"ukumari:\n{shown}{more}"
        )
