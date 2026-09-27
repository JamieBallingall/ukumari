"""The layout: where each cell goes.

It is kept apart from the circuit: delete it and the circuit computes the same values. It is
given at the vector level and turned into cell addresses once extents are known.

The default layout is one sheet, ``Model``:

- periods run across columns, one column per axis position, from column B; a vector starts
  at the column where its region starts, so a forecast sits under the forecast years;
- scalars sit in the first period column;
- row 1 is a spine, ``P1``, ``P2``, … over the period columns;
- labels are in column A;
- ``rows`` orders and groups the rows; rows it does not name come below, one vector per row,
  in declaration order, labelled by name.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from ukumari.circuit import Circuit
from ukumari.shape import Interval

FIRST_PERIOD_COLUMN = 2


@dataclass(frozen=True, slots=True)
class Layout:
    """How to lay a model out, at the vector level.

    ``rows`` maps a row label to the vectors sharing that row. ``formats`` maps a row label
    to a number-format code for that row's value cells; an unformatted row is ``General``,
    deliberately, since a blanket format would round a 1e-11 balance residual into a
    reassuring zero. ``indents`` maps a row label to an indent level for its label cell.
    ``label_width`` and ``period_width`` set column widths; unset means the app's default.
    """

    rows: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    formats: Mapping[str, str] = field(default_factory=dict)
    indents: Mapping[str, int] = field(default_factory=dict)
    label_width: float | None = None
    period_width: float | None = None
    sheet: str = "Model"


@dataclass(frozen=True, slots=True)
class Row:
    number: int
    label: str
    names: tuple[str, ...]
    number_format: str | None
    indent: int | None


@dataclass(frozen=True, slots=True)
class Grid:
    """A layout resolved against extents: every row, and the address of every cell."""

    sheet: str
    rows: tuple[Row, ...]
    periods: int
    label_width: float | None
    period_width: float | None
    row_of: Mapping[str, Row]

    def address(self, name: str, position: int | None) -> tuple[int, int]:
        """The (row, column) of a cell: a vector's position, or a scalar (``None``)."""
        column = FIRST_PERIOD_COLUMN + (0 if position is None else position)
        return self.row_of[name].number, column


def grid(
    layout: Layout, circuit: Circuit, intervals: Mapping[str, Interval | None]
) -> Grid:
    """Resolve a layout against the intervals binding gave every declared name.

    A layout is written by hand, so a mistake in it (an unknown name, a name in two rows,
    two members of a row that would overlap) raises ``ValueError``.
    """
    declared = [d.name for d in circuit.declarations]
    known = set(declared)
    problems: list[str] = []
    placed: dict[str, str] = {}
    for label, names in layout.rows.items():
        if not label:
            problems.append("a row label must not be empty")
        for name in names:
            if name not in known:
                problems.append(f"row {label!r} names {name!r}, which is not declared")
            elif name in placed:
                problems.append(
                    f"{name!r} is in two rows, {placed[name]!r} and {label!r}"
                )
            else:
                placed[name] = label
    for option, labels in (("formats", layout.formats), ("indents", layout.indents)):
        for label in labels:
            if label not in layout.rows:
                problems.append(f"{option} names row {label!r}, which is not in rows")

    specified = [(label, tuple(names)) for label, names in layout.rows.items()]
    rest = [(name, (name,)) for name in declared if name not in placed]
    rows: list[Row] = []
    for offset, (label, names) in enumerate(specified + rest):
        columns: dict[int, str] = {}
        for name in names:
            if name not in known:
                continue
            interval = intervals[name]
            span = (
                range(1) if interval is None else range(interval.start, interval.stop)
            )
            for position in span:
                if position in columns:
                    problems.append(
                        f"row {label!r}: {columns[position]!r} and {name!r} would "
                        f"overlap in period {position + 1}"
                    )
                    break
                columns[position] = name
        rows.append(
            Row(
                number=offset + 2,
                label=label,
                names=names,
                number_format=layout.formats.get(label),
                indent=layout.indents.get(label),
            )
        )
    if problems:
        raise ValueError("the layout is wrong:\n" + "\n".join(problems))

    periods = max(
        (i.stop for i in intervals.values() if i is not None),
        default=1,
    )
    return Grid(
        sheet=layout.sheet,
        rows=tuple(rows),
        periods=periods,
        label_width=layout.label_width,
        period_width=layout.period_width,
        row_of={name: row for row in rows for name in row.names},
    )
