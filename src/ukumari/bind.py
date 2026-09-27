"""The data gate: binding L to data gives V.

Binding gives every region an extent and rejects only data, since the model was fully
checked before L existed:

1. every region's extent, from the lengths of the inputs on it or given explicitly;
2. every span resolved to an absolute interval;
3. the data checked to fit;
4. every recurrence written out position by position. Each member of a recurrent component
   gets one small equation per position, whose leaves are literals, ``At(name, position)``,
   single values and reductions. A lag becomes an ``At`` one position back, which is where
   the cycles leave: V is acyclic. Vectors outside every component stay whole.

``at_position`` is the one function that reads a ``lag``; the unroll uses it too.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from yupana.result import Err, Ok, Result

from ukumari._runtime import _extents, _placement
from ukumari.circuit import Circuit, Kind
from ukumari.expr import At, Binary, Expr, First, Lag, Last, Literal, Neg, Ref
from ukumari.shape import Axis, Interval, Scalar, Shape, Span


@dataclass(frozen=True, slots=True)
class MissingExtent:
    region: str

    def __str__(self) -> str:
        return f"nothing gives region {self.region!r} a length: give its extent"


@dataclass(frozen=True, slots=True)
class ConflictingExtent:
    """Sources that disagree: input names, or ``""`` for the extents given explicitly."""

    region: str
    sources: tuple[tuple[str, int], ...]

    def __str__(self) -> str:
        told = ", ".join(
            f"{extent} from {repr(source) if source else 'the extents given'}"
            for source, extent in self.sources
        )
        return f"region {self.region!r} is given different lengths: {told}"


@dataclass(frozen=True, slots=True)
class EmptyRegion:
    """A span trimmed to nothing, or (when ``name`` is the region) a region of no positions."""

    name: str
    region: str

    def __str__(self) -> str:
        if self.name == self.region:
            return f"region {self.region!r} has no positions"
        return f"{self.name!r} is trimmed to nothing on region {self.region!r}"


@dataclass(frozen=True, slots=True)
class MissingInput:
    name: str

    def __str__(self) -> str:
        return f"input {self.name!r} is missing"


@dataclass(frozen=True, slots=True)
class WrongLength:
    name: str
    expected: int
    got: int

    def __str__(self) -> str:
        return f"input {self.name!r} needs {self.expected} value(s), not {self.got}"


@dataclass(frozen=True, slots=True)
class UnknownInput:
    name: str

    def __str__(self) -> str:
        return f"{self.name!r} is not an input of this model"


@dataclass(frozen=True, slots=True)
class UnknownExtent:
    region: str

    def __str__(self) -> str:
        return f"an extent is given for {self.region!r}, which is not a region"


type DataError = (
    MissingExtent
    | ConflictingExtent
    | EmptyRegion
    | MissingInput
    | WrongLength
    | UnknownInput
    | UnknownExtent
)


def _data_error(problem: tuple) -> DataError:
    match problem:
        case ("missing_extent", region):
            return MissingExtent(region)
        case ("conflicting_extent", region, sources):
            return ConflictingExtent(region, sources)
        case ("empty_region", name, region):
            return EmptyRegion(name, region)
        case ("missing_input", name):
            return MissingInput(name)
        case ("wrong_length", name, expected, got):
            return WrongLength(name, expected, got)
        case ("unknown_input", name):
            return UnknownInput(name)
        case ("unknown_extent", region):
            return UnknownExtent(region)
    raise AssertionError(f"an unexpected problem from the data gate: {problem!r}")


def declaration_table(
    circuit: Circuit,
) -> tuple[tuple[str, str, str | None, int, int], ...]:
    """Declarations as the runtime reads them: ``(name, kind, region, front, back)``."""
    rows: list[tuple[str, str, str | None, int, int]] = []
    for d in circuit.declarations:
        match d.shape:
            case Scalar():
                rows.append((d.name, str(d.kind), None, 0, 0))
            case Span(region, front, back):
                rows.append((d.name, str(d.kind), region, front, back))
    return tuple(rows)


def axis_table(axes: tuple[Axis, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((axis.name, axis.regions) for axis in axes)


@dataclass(frozen=True, slots=True)
class Whole:
    """A vector outside every component, computed whole from its equation."""

    expression: Expr


@dataclass(frozen=True, slots=True)
class Written:
    """A member of a recurrence, written out: one equation per position of its interval."""

    positions: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class Bound:
    """V: L bound to data. Every length is known and every recurrence is written out."""

    circuit: Circuit
    extents: Mapping[str, int]
    intervals: Mapping[str, Interval | None]
    inputs: Mapping[str, tuple[float, ...]]
    equations: Mapping[str, Whole | Written]


def at_position(expr: Expr, t: int, first: int, shapes: Mapping[str, Shape]) -> Expr:
    """An expression written out at absolute position ``t``: the one reader of ``lag``.

    ``first`` is the first position the expression is asked for. A seeded lag gives its seed
    there and the previous position of its body after; an unseeded lag always reads the
    previous position, so under it the body is asked from one position earlier.

    >>> shapes = {"x": Span("r"), "k": Scalar()}
    >>> at_position(Lag(Ref("x"), Ref("k")), 3, 3, shapes)
    Ref(name='k')
    >>> at_position(Lag(Ref("x"), Ref("k")), 5, 3, shapes)
    At(name='x', position=4)

    Under an unseeded lag, the inner lag is asked from one position earlier, so
    ``lag(lag(x, seed=k))`` is ``k`` at the first position and ``x`` two back after it:

    >>> twice = Lag(Lag(Ref("x"), Ref("k")), None)
    >>> at_position(twice, 3, 3, shapes), at_position(twice, 4, 3, shapes)
    (Ref(name='k'), At(name='x', position=2))
    """
    match expr:
        case Literal() | Last() | First():
            return expr
        case Ref(name):
            return expr if isinstance(shapes[name], Scalar) else At(name, t)
        case At():
            raise AssertionError("a checked model holds no At")
        case Neg(operand):
            return Neg(at_position(operand, t, first, shapes))
        case Binary(op, left, right):
            return Binary(
                op,
                at_position(left, t, first, shapes),
                at_position(right, t, first, shapes),
            )
        case Lag(body, seed):
            if seed is None:
                return at_position(body, t - 1, first - 1, shapes)
            if t == first:
                return at_position(seed, t, first, shapes)
            return at_position(body, t - 1, first, shapes)


def bind(
    circuit: Circuit,
    inputs: Mapping[str, Sequence[float]],
    extents: Mapping[str, int] | None = None,
) -> Result[Bound, tuple[DataError, ...]]:
    """V, or every problem with the data at once.

    An input value that is infinite is read as the error value.
    """
    declarations = declaration_table(circuit)
    axes = axis_table(circuit.axes)
    lengths = {name: len(values) for name, values in inputs.items()}
    found, problems = _extents(declarations, axes, lengths, dict(extents or {}))
    if problems:
        return Err(tuple(_data_error(p) for p in problems))

    places = _placement(declarations, axes, found)
    axis_of = {region: axis.name for axis in circuit.axes for region in axis.regions}
    intervals: dict[str, Interval | None] = {}
    for (name, _, region, _, _), place in zip(declarations, places, strict=True):
        if region is None or place is None:
            intervals[name] = None
        else:
            intervals[name] = Interval(axis_of[region], place[0], place[1])

    values = {
        d.name: tuple(_read(v) for v in inputs[d.name])
        for d in circuit.declarations
        if d.kind is Kind.INPUT
    }
    shapes = circuit.shapes()
    definitions = circuit.definitions()
    equations: dict[str, Whole | Written] = {}
    for layer in circuit.schedule:
        for component in layer.components:
            for name in component.members:
                interval = intervals[name]
                if component.recurrent and interval is not None:
                    positions = tuple(
                        at_position(definitions[name], t, interval.start, shapes)
                        for t in range(interval.start, interval.stop)
                    )
                    equations[name] = Written(positions)
                else:
                    equations[name] = Whole(definitions[name])
    return Ok(Bound(circuit, found, intervals, values, equations))


def _read(value: float) -> float:
    x = float(value)
    return math.nan if math.isinf(x) else x
