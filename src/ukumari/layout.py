"""The layout: where each cell goes.

It is kept apart from the circuit: delete it and the circuit computes the same values. It is
given at the vector level and turned into cell addresses once extents are known. It comes in
two forms.

A ``Layout`` is one sheet, ``Model`` by default:

- periods run across columns, one column per axis position, from column B; a vector starts
  at the column where its region starts, so a forecast sits under the forecast years;
- scalars sit in the first period column;
- row 1 is a spine, ``P1``, ``P2``, … over the period columns;
- labels are in column A;
- ``rows`` orders and groups the rows; rows it does not name come below, one vector per row,
  in declaration order, labelled by name.

A ``Workbook`` is several sheets. Each is a list of rows from row 1 down: lines of values,
headings and blank rows. On every sheet, labels are in column A, single values in column B,
and periods run from column C, which shows the first position of the sheet's ``start``
region. So sheets that start at the same region line up column for column, and a row copied
from one to the other is a link to the same column. Every declared name is on exactly one
sheet.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from ukumari.bind import Bound
from ukumari.shape import place

FIRST_PERIOD_COLUMN = 2
VALUE_COLUMN = 2


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


@dataclass(frozen=True, slots=True)
class Layout:
    """How to lay a model out on one sheet, at the vector level.

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
class Line:
    """A row of values: its label, and the declared names whose cells it holds.

    Its value cells take ``number_format`` (``General`` when unset, as in ``Layout``), and
    its label is indented by ``indent``.
    """

    label: str
    names: tuple[str, ...]
    number_format: str | None = None
    indent: int | None = None


@dataclass(frozen=True, slots=True)
class Heading:
    """A row holding only its label: the title of the rows below it."""

    label: str


@dataclass(frozen=True, slots=True)
class Blank:
    """An empty row."""


type Item = Line | Heading | Blank


@dataclass(frozen=True, slots=True)
class Sheet:
    """One sheet of a workbook: its name, and its rows from row 1 down.

    Column C shows the first position of the region ``start``, or the first position of the
    axis when it is None. ``label_width`` sets column A's width, and ``period_width`` every
    other column's; unset means the app's default.
    """

    name: str
    items: tuple[Item, ...]
    start: str | None = None
    label_width: float | None = None
    period_width: float | None = None


@dataclass(frozen=True, slots=True)
class Workbook:
    """How to lay a model out over several sheets, in the order they appear."""

    sheets: tuple[Sheet, ...]


@dataclass(frozen=True, slots=True)
class Row:
    """A labelled row: a line of values, or a heading, which holds no names."""

    sheet: str
    number: int
    label: str
    names: tuple[str, ...]
    number_format: str | None
    indent: int | None


@dataclass(frozen=True, slots=True)
class Page:
    """A sheet, resolved: its labelled rows, and which column shows which position.

    ``spine`` is how many period columns row 1 labels ``P1``, ``P2``, …; 0 for none.
    """

    name: str
    rows: tuple[Row, ...]
    spine: int
    value_column: int
    first_period_column: int
    start: int
    label_width: float | None
    period_width: float | None

    def column(self, position: int | None) -> int:
        """The column of a position on the axis, or of a single value (``None``)."""
        if position is None:
            return self.value_column
        return self.first_period_column + position - self.start


@dataclass(frozen=True, slots=True)
class Address:
    sheet: str
    row: int
    column: int


@dataclass(frozen=True, slots=True)
class Grid:
    """A layout resolved against extents: every sheet, and the address of every cell."""

    pages: tuple[Page, ...]
    row_of: Mapping[str, Row]
    page_of: Mapping[str, Page]

    @property
    def rows(self) -> tuple[Row, ...]:
        return tuple(row for page in self.pages for row in page.rows)

    def address(self, name: str, position: int | None) -> Address:
        """Where a cell is: a vector's position, or a single value (``None``)."""
        row = self.row_of[name]
        return Address(row.sheet, row.number, self.page_of[row.sheet].column(position))


@dataclass(frozen=True, slots=True)
class _Plan:
    """A sheet before resolution: what either form of layout gives the common steps."""

    name: str
    items: tuple[Item, ...]
    first_row: int
    spine: bool
    value_column: int
    first_period_column: int
    start: str | None
    label_width: float | None
    period_width: float | None


def _one_sheet(layout: Layout, declared: Sequence[str]) -> tuple[_Plan, list[str]]:
    """A ``Layout`` as a plan, the names it leaves out appended, and its own problems."""
    problems: list[str] = []
    for option, labels in (("formats", layout.formats), ("indents", layout.indents)):
        for label in labels:
            if label not in layout.rows:
                problems.append(f"{option} names row {label!r}, which is not in rows")
    named = {name for names in layout.rows.values() for name in names}
    items: list[Item] = [
        Line(label, tuple(names), layout.formats.get(label), layout.indents.get(label))
        for label, names in layout.rows.items()
    ]
    items += [Line(name, (name,)) for name in declared if name not in named]
    plan = _Plan(
        name=layout.sheet,
        items=tuple(items),
        first_row=2,
        spine=True,
        value_column=FIRST_PERIOD_COLUMN,
        first_period_column=FIRST_PERIOD_COLUMN,
        start=None,
        label_width=layout.label_width,
        period_width=layout.period_width,
    )
    return plan, problems


def _sheets(
    workbook: Workbook, regions: Sequence[str]
) -> tuple[list[_Plan], list[str]]:
    """A ``Workbook``'s sheets as plans, and its own problems."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for sheet in workbook.sheets:
        # The app compares sheet names ignoring case, so these would be one sheet.
        folded = sheet.name.casefold()
        if folded in seen:
            problems.append(f"sheets {seen[folded]!r} and {sheet.name!r} are one sheet")
        seen.setdefault(folded, sheet.name)
        if sheet.start is not None and sheet.start not in regions:
            problems.append(
                f"sheet {sheet.name!r} starts at {sheet.start!r}, which is not a region"
            )
    if not workbook.sheets:
        problems.append("a workbook needs at least one sheet")
    plans = [
        _Plan(
            name=sheet.name,
            items=sheet.items,
            first_row=1,
            spine=False,
            value_column=VALUE_COLUMN,
            first_period_column=VALUE_COLUMN + 1,
            start=sheet.start,
            label_width=sheet.label_width,
            period_width=sheet.period_width,
        )
        for sheet in workbook.sheets
    ]
    return plans, problems


def grid(layout: Layout | Workbook, bound: Bound) -> Grid:
    """Resolve a layout against the intervals binding gave every declared name.

    A layout is written by hand, so a mistake in it (an unknown name, a name in two rows or
    on no sheet, two members of a row that would overlap, a vector that starts left of its
    sheet's first period column) raises ``ValueError``.
    """
    circuit = bound.circuit
    declared = [d.name for d in circuit.declarations]
    known = set(declared)
    regions = [region for axis in circuit.axes for region in axis.regions]
    match layout:
        case Layout():
            plan, problems = _one_sheet(layout, declared)
            plans = [plan]
        case Workbook():
            plans, problems = _sheets(layout, regions)
    starts = {
        region: i.start for region, i in place(circuit.axes, bound.extents).items()
    }
    periods = max(
        (i.stop for i in bound.intervals.values() if i is not None), default=1
    )

    placed: dict[str, str] = {}
    pages: list[Page] = []
    for plan in plans:
        page = Page(
            name=plan.name,
            rows=(),
            spine=periods if plan.spine else 0,
            value_column=plan.value_column,
            first_period_column=plan.first_period_column,
            start=0 if plan.start is None else starts.get(plan.start, 0),
            label_width=plan.label_width,
            period_width=plan.period_width,
        )
        rows: list[Row] = []
        for offset, item in enumerate(plan.items):
            match item:
                case Blank():
                    continue
                case Heading(label):
                    line = Line(label, ())
                case Line():
                    line = item
            where = f"row {line.label!r}"
            if len(plans) > 1:
                where = f"sheet {plan.name!r}, {where}"
            if not line.label:
                problems.append(f"{where}: a row label must not be empty")
            columns: dict[int, str] = {}
            for name in line.names:
                if name not in known:
                    problems.append(f"{where} names {name!r}, which is not declared")
                    continue
                if name in placed:
                    problems.append(
                        f"{name!r} is in two rows, {placed[name]!r} and {line.label!r}"
                    )
                    continue
                placed[name] = line.label
                interval = bound.intervals[name]
                if interval is None:
                    positions: list[int | None] = [None]
                elif interval.start < page.start:
                    problems.append(
                        f"{where}: {name!r} starts left of the first period column"
                    )
                    continue
                else:
                    positions = list(range(interval.start, interval.stop))
                for position in positions:
                    column = page.column(position)
                    if column in columns:
                        problems.append(
                            f"{where}: {columns[column]!r} and {name!r} would overlap "
                            f"in column {column_letters(column)}"
                        )
                        break
                    columns[column] = name
            number = plan.first_row + offset
            rows.append(
                Row(
                    plan.name,
                    number,
                    line.label,
                    line.names,
                    line.number_format,
                    line.indent,
                )
            )
        pages.append(replace(page, rows=tuple(rows)))
    for name in declared:
        if name not in placed:
            problems.append(f"{name!r} is on no sheet")
    if problems:
        raise ValueError("the layout is wrong:\n" + "\n".join(problems))
    return Grid(
        pages=tuple(pages),
        row_of={name: row for page in pages for row in page.rows for name in row.names},
        page_of={page.name: page for page in pages},
    )
