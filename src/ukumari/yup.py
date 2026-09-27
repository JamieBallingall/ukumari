"""β₁: writing S and a layout as ``.yup``, and the values CSV beside it.

- **A cell whose equation is a bare reference** (a copy, the previous position of a lag, a
  seed, a reduction) is a link to the cell it reads: the lag edge ``opening[1]`` is
  ``closing[0]``, so it is ``=B7``, and a copy of a copy links to the copy it was made from.
  **Every other cell writes out its own equation**, even where the same value is computed
  elsewhere, so a row that computes the same thing in every column reads the same in every
  column.
- **A formula is its equation.** It references exactly the cells its equation names, and
  writes every operation inline, even one another cell happens to compute: sharing nodes
  is how S computes each value once, not how a modeller writes. So a whole subtree becomes
  ``=B2*C2+D2``, not one cell per operation, and ``closing[1] = opening[1] − payment[1]``
  is written ``=C3-C4``, with both operands from the period-1 column; a seed is read from
  the cell the model names, not from the input that first held its value.
- **Among several named cells holding one value**, the first of these groups that has one:
  the formula's own column on its own sheet; its own sheet; the same position on another
  sheet; the rest. Within a group, the origin first, then unroll order.
- **A reference to another sheet** names it in single quotes, ``'Assumptions'!C8``, with
  any apostrophe doubled.
- **A reference to a single value is absolute**, ``$B$7``, as a modeller writes a link to
  an assumption, so a row that uses it reads the same in every column.
- A cell whose node is a lone literal (a seed) holds the number. Input cells hold their data
  as numbers; the error value is written ``=NA()``, since ``.yup`` has no error constants.
- **Order**, so every formula refers only to earlier lines: text cells sheet by sheet and row
  by row, then every node-holding cell in ascending node id, each node's origin before its
  other holders. Sheets appear in the workbook in the order of their first line, so the
  text cells put them in the layout's order.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from yupana import PREAMBLE, Type, Value, write_values

from ukumari.bind import Bound
from ukumari.layout import Address, Grid, column_letters
from ukumari.unroll import Cell, Const, Element, Operation, Prim, Straight

_SYMBOL = {Prim.ADD: "+", Prim.SUB: "-", Prim.MUL: "*", Prim.DIV: "/", Prim.POW: "^"}
_BINDING = {Prim.ADD: 1, Prim.SUB: 1, Prim.MUL: 2, Prim.DIV: 2}
_POWER = 3
_NEGATION = 4
_ATOM = 5


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


def sheet_prefix(sheet: str) -> str:
    """How a formula on another sheet names this one.

    >>> sheet_prefix("Assumptions"), sheet_prefix("It's here")
    ("'Assumptions'!", "'It''s here'!")
    """
    quoted = sheet.replace("'", "''")
    return f"'{quoted}'!"


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
    address = {cell: grid.address(*cell) for cell in s.cells}

    def link(target: Cell, here: Address) -> str:
        at = address[target]
        prefix = "" if at.sheet == here.sheet else sheet_prefix(at.sheet)
        anchor = "$" if target[1] is None else ""
        return f"{prefix}{anchor}{column_letters(at.column)}{anchor}{at.row}"

    def reference(node: int, cell: Cell, found: list[Cell]) -> str:
        here = address[cell]
        origin = s.origins[node]
        on_sheet = [c for c in found if address[c].sheet == here.sheet]
        tiers = (
            [c for c in on_sheet if address[c].column == here.column],
            on_sheet,
            [c for c in found if c[1] == cell[1]],
            found,
        )
        chosen = next(tier for tier in tiers if tier)
        return link(origin if origin in chosen else chosen[0], here)

    def render(node: int, cell: Cell, top: bool) -> tuple[str, int]:
        """Formula text for a node, and how tightly it binds."""
        if not top:
            named = [c for c in s.reads[cell] if s.cells[c] == node]
            if named:
                return reference(node, cell, named), _ATOM
        match s.nodes[node]:
            case Const(value):
                if math.isnan(value):
                    return "NA()", _ATOM
                text = literal(value)
                return (f"({text})", _ATOM) if value < 0 else (text, _ATOM)
            case Element():
                raise AssertionError("an input is read only through a cell it names")
            case Operation(Prim.NEG, (operand,)):
                text, binding = render(operand, cell, False)
                if binding <= _NEGATION:
                    text = f"({text})"
                return f"-{text}", _NEGATION
            case Operation(Prim.MIN | Prim.MAX as prim, (a, b)):
                left, _ = render(a, cell, False)
                right, _ = render(b, cell, False)
                return f"{prim.upper()}({left},{right})", _ATOM
            case Operation(Prim.POW, (a, b)):
                # The app binds negation more tightly than ^ (=-2^2 is 4) and reads a^b^c
                # from the left, so every operand but a reference, a call or a number is
                # bracketed, and so is the power itself wherever it is negated.
                left, left_binding = render(a, cell, False)
                right, right_binding = render(b, cell, False)
                if left_binding < _ATOM:
                    left = f"({left})"
                if right_binding < _ATOM:
                    right = f"({right})"
                return f"{left}^{right}", _POWER
            case Operation(prim, (a, b)):
                binding = _BINDING[prim]
                left, left_binding = render(a, cell, False)
                right, right_binding = render(b, cell, False)
                if left_binding < binding:
                    left = f"({left})"
                if right_binding <= binding:
                    right = f"({right})"
                return f"{left}{_SYMBOL[prim]}{right}", binding
            case Operation():
                raise AssertionError(f"a malformed node: {s.nodes[node]}")

    def content(cell: Cell) -> str:
        if cell in s.sources:
            return f"={link(s.sources[cell], address[cell])}"
        node = s.cells[cell]
        match s.nodes[node]:
            case Const(value):
                return "=NA()" if math.isnan(value) else f"#{number(value)}"
            case Element(name, index):
                value = bound.inputs[name][index]
                return "=NA()" if math.isnan(value) else f"#{number(value)}"
            case Operation():
                text, _ = render(node, cell, True)
                return f"={text}"

    lines: list[str] = []
    value_rows: list[Value] = []
    widths_written: set[tuple[str, int]] = set()

    def emit(
        at: Address, cell_text: str, formats: list[str], value: tuple[int, str]
    ) -> None:
        pairs = []
        if (at.sheet, at.column) not in widths_written:
            widths_written.add((at.sheet, at.column))
            page = grid.page_of[at.sheet]
            width = page.label_width if at.column == 1 else page.period_width
            pairs.append(f"columnwidth={_width(width)}")
        pairs += formats
        lines.append(
            f"{at.sheet}\t{at.row}\t{at.column}\t{cell_text}\t{'|'.join(pairs)}"
        )
        value_rows.append(Value(at.sheet, at.row, at.column, Type(value[0]), value[1]))

    for page in grid.pages:
        for period in range(page.spine):
            text = f"P{period + 1}"
            spine = Address(page.name, 1, page.first_period_column + period)
            emit(spine, f"${text}", [], (2, text))
        for row in page.rows:
            indent = [] if row.indent is None else [f"indent={row.indent}"]
            emit(
                Address(page.name, row.number, 1),
                f"${row.label}",
                indent,
                (2, row.label),
            )

    order = sorted(
        s.cells,
        key=lambda cell: (s.cells[cell], cell != s.origins[s.cells[cell]]),
    )
    for cell in order:
        name = cell[0]
        number_format = grid.row_of[name].number_format
        formats = [] if number_format is None else [f"numberformat={number_format}"]
        value = values[cell]
        typed = (16, "#N/A") if math.isnan(value) else (1, number(value))
        emit(address[cell], content(cell), formats, typed)
    return Written(PREAMBLE + "\n".join(lines) + "\n", write_values(value_rows))
