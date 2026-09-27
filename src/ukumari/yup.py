"""β₁: writing S and a layout as ``.yup``, and the values CSV beside it.

- **Which cell holds the formula for a node:** its origin. Another cell holding the same node
  (the lag edge: ``opening[1]`` is ``closing[0]``) points at the origin: ``=B7``.
- **Which cell a formula references for a node:** the one in the same period column where
  there is one, otherwise the origin. So ``closing[1] = opening[1] − payment[1]`` is written
  ``=C3-C4``, with both operands from the period-1 column, as a modeller writes it.
- **A cell's formula renders its node's expression.** Every operand node that has a cell
  becomes a reference; operand nodes without one are written inline, so a whole subtree
  becomes ``=B2*C2+D2``, not one cell per operation.
- A cell whose node is a lone literal (a seed) holds the number. Input cells hold their data
  as numbers; the error value is written ``=NA()``, since ``.yup`` has no error constants.
- **Order**, so every formula refers only to earlier lines: text cells row by row, then every
  node-holding cell in ascending node id, each node's origin before its other holders.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from ukumari.bind import Bound
from ukumari.layout import FIRST_PERIOD_COLUMN, Grid
from ukumari.unroll import Cell, Const, Element, Operation, Prim, Straight
from ukumari.yupana_stand_in import write_values

_SYMBOL = {Prim.ADD: "+", Prim.SUB: "-", Prim.MUL: "*", Prim.DIV: "/"}
_BINDING = {Prim.ADD: 1, Prim.SUB: 1, Prim.MUL: 2, Prim.DIV: 2}
_NEGATION = 3
_ATOM = 4


def column_letters(column: int) -> str:
    """Bijective base 26: 1 is ``A``, 26 is ``Z``, 27 is ``AA``.

    >>> column_letters(1), column_letters(26), column_letters(27), column_letters(16384)
    ('A', 'Z', 'AA', 'XFD')
    """
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def literal(value: float) -> str:
    """The shortest text that reads back as the same double.

    An integral value is plain digits unless its ``repr`` is shorter, so ``2.0`` is ``2``
    but ``1e16`` stays ``1E+16`` rather than seventeen digits.

    >>> literal(2.0), literal(0.1), literal(1e-05), literal(1.5e300), literal(-3.0)
    ('2', '0.1', '1E-05', '1.5E+300', '-3')
    >>> literal(123456789012345.0), literal(1e16)
    ('123456789012345', '1E+16')
    """
    written = repr(value).replace("e", "E")
    if value == int(value) and len(digits := str(int(value))) <= len(written):
        return digits
    return written


def number(value: float) -> str:
    """A number cell's text: Python's ``repr``, which is in JSON's grammar when finite."""
    return repr(value)


def _width(value: float | None) -> str:
    if value is None:
        return "default"
    return str(int(value)) if value == int(value) else repr(value)


@dataclass(frozen=True, slots=True)
class Written:
    """A ``.yup`` file and, beside it, the values CSV, in the same order."""

    yup: str
    values: str


def write_yup(
    s: Straight, bound: Bound, grid: Grid, values: Mapping[Cell, float]
) -> Written:
    """The ``.yup`` text and values CSV for S laid out on a grid.

    ``values`` holds P's value for every cell; the values CSV carries them.
    """
    holders: dict[int, list[Cell]] = {}
    for cell, node in s.cells.items():
        holders.setdefault(node, []).append(cell)
    address = {cell: grid.address(*cell) for cell in s.cells}

    def reference(node: int, column: int) -> str:
        here = [c for c in holders[node] if address[c][1] == column]
        origin = s.origins[node]
        chosen = origin if origin in here else (here[0] if here else origin)
        row, col = address[chosen]
        return f"{column_letters(col)}{row}"

    def render(node: int, column: int, top: bool) -> tuple[str, int]:
        """Formula text for a node, and how tightly it binds."""
        if not top and node in holders:
            return reference(node, column), _ATOM
        match s.nodes[node]:
            case Const(value):
                if math.isnan(value):
                    return "NA()", _ATOM
                text = literal(value)
                return (f"({text})", _ATOM) if value < 0 else (text, _ATOM)
            case Element():
                raise AssertionError("every input element has a cell")
            case Operation(Prim.NEG, (operand,)):
                text, binding = render(operand, column, False)
                if binding <= _NEGATION:
                    text = f"({text})"
                return f"-{text}", _NEGATION
            case Operation(Prim.MIN | Prim.MAX as prim, (a, b)):
                left, _ = render(a, column, False)
                right, _ = render(b, column, False)
                return f"{prim.upper()}({left},{right})", _ATOM
            case Operation(prim, (a, b)):
                binding = _BINDING[prim]
                left, left_binding = render(a, column, False)
                right, right_binding = render(b, column, False)
                if left_binding < binding:
                    left = f"({left})"
                if right_binding <= binding:
                    right = f"({right})"
                return f"{left}{_SYMBOL[prim]}{right}", binding
            case Operation():
                raise AssertionError(f"a malformed node: {s.nodes[node]}")

    def content(cell: Cell) -> str:
        node = s.cells[cell]
        origin = s.origins[node]
        if cell != origin:
            row, col = address[origin]
            return f"={column_letters(col)}{row}"
        match s.nodes[node]:
            case Const(value):
                return "=NA()" if math.isnan(value) else f"#{number(value)}"
            case Element(name, index):
                value = bound.inputs[name][index]
                return "=NA()" if math.isnan(value) else f"#{number(value)}"
            case Operation():
                text, _ = render(node, address[cell][1], True)
                return f"={text}"

    lines = ["sheet\trow\tcol\tcell\tformat"]
    value_rows: list[tuple[str, int, int, int, str]] = []
    widths_written: set[int] = set()
    sheet = grid.sheet

    def emit(
        row: int, col: int, cell_text: str, formats: list[str], value: tuple[int, str]
    ) -> None:
        pairs = []
        if col not in widths_written:
            widths_written.add(col)
            width = grid.label_width if col == 1 else grid.period_width
            pairs.append(f"columnwidth={_width(width)}")
        pairs += formats
        lines.append(f"{sheet}\t{row}\t{col}\t{cell_text}\t{'|'.join(pairs)}")
        value_rows.append((sheet, row, col, *value))

    for period in range(grid.periods):
        text = f"P{period + 1}"
        emit(1, FIRST_PERIOD_COLUMN + period, f"${text}", [], (2, text))
    for row in grid.rows:
        indent = [] if row.indent is None else [f"indent={row.indent}"]
        emit(row.number, 1, f"${row.label}", indent, (2, row.label))

    order = sorted(
        s.cells,
        key=lambda cell: (s.cells[cell], cell != s.origins[s.cells[cell]]),
    )
    for cell in order:
        row, col = address[cell]
        name = cell[0]
        number_format = grid.row_of[name].number_format
        formats = [] if number_format is None else [f"numberformat={number_format}"]
        value = values[cell]
        typed = (16, "#N/A") if math.isnan(value) else (1, number(value))
        emit(row, col, content(cell), formats, typed)
    return Written("\n".join(lines) + "\n", write_values(value_rows))
