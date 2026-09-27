"""Alignment, decided with no extents at all.

Values line up by position, never by coincidence. An equation defining a vector on span T
needs a value from each leaf at every position of T (shifted by any lags above the leaf). A
leaf that is a region vector must contain those positions, on the same axis; a scalar leaf
supplies every position; a scalar equation reads a region vector only through a reduction.

A position is a linear form in the region extents: the extents of the regions before it on
its axis, plus a constant from trims and lags. Every check asks whether a form is
non-negative for every admissible choice of extents. The admissible extents form a box:
every declared span keeps at least one element, so each region has a minimum extent and no
maximum. On a box the answer is exact: the form is non-negative everywhere if and only if
every coefficient is non-negative and the form is non-negative at the minimum corner.

One refinement keeps it exact. A seeded lag over a one-element target asks its body for
nothing, so what lies under ``k`` seeded lags is checked only where the target has more than
``k`` elements. That condition involves the target's region alone, so it raises that
region's minimum and the domain stays a box.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from ukumari.circuit import Equation
from ukumari.errors import (
    AlignmentError,
    LagBeforeStart,
    LagOffAxis,
    Misaligned,
    ReductionOfAScalar,
    SeedNotScalar,
)
from ukumari.expr import At, Binary, Expr, First, Lag, Last, Literal, Neg, Ref
from ukumari.shape import Axis, Scalar, Shape, Span


@dataclass(frozen=True, slots=True)
class Form:
    """A linear form in region extents: ``sum(coefficient * extent) + constant``.

    >>> f = Form.extent("a") + Form.extent("b") - Form.extent("a") - 3
    >>> f
    Form(coefficients=(('b', 1),), constant=-3)
    >>> f.nonnegative({"a": 1, "b": 3}), f.nonnegative({"a": 1, "b": 2})
    (True, False)
    """

    coefficients: tuple[tuple[str, int], ...]
    constant: int

    @staticmethod
    def extent(region: str) -> Form:
        return Form(((region, 1),), 0)

    def __add__(self, other: Form | int) -> Form:
        if isinstance(other, int):
            return Form(self.coefficients, self.constant + other)
        merged = dict(self.coefficients)
        for region, c in other.coefficients:
            merged[region] = merged.get(region, 0) + c
        kept = tuple(sorted((r, c) for r, c in merged.items() if c != 0))
        return Form(kept, self.constant + other.constant)

    def __neg__(self) -> Form:
        return Form(tuple((r, -c) for r, c in self.coefficients), -self.constant)

    def __sub__(self, other: Form | int) -> Form:
        return self + (-other)

    def nonnegative(self, minimum: Mapping[str, int]) -> bool:
        """Whether the form is non-negative for every extent at or above ``minimum``."""
        if any(c < 0 for _, c in self.coefficients):
            return False
        at_corner = sum(c * minimum[r] for r, c in self.coefficients)
        return at_corner + self.constant >= 0


ZERO = Form((), 0)


def minimum_extents(
    axes: tuple[Axis, ...], shapes: Mapping[str, Shape]
) -> dict[str, int]:
    """The smallest extent of each placed region the data gate accepts.

    A region has at least one position, and every declared span on it keeps at least one.
    """
    minimum = {region: 1 for axis in axes for region in axis.regions}
    for shape in shapes.values():
        if isinstance(shape, Span) and shape.region in minimum:
            need = shape.front + shape.back + 1
            minimum[shape.region] = max(minimum[shape.region], need)
    return minimum


@dataclass(frozen=True, slots=True)
class _Axes:
    """What alignment knows about placement, before any extent is known."""

    shapes: Mapping[str, Shape]
    axis_of: Mapping[str, str]
    offset: Mapping[str, Form]
    minimum: Mapping[str, int]

    def placed(self, name: str) -> Span | None:
        shape = self.shapes.get(name)
        if isinstance(shape, Span) and shape.region in self.axis_of:
            return shape
        return None

    def start(self, span: Span) -> Form:
        return self.offset[span.region] + span.front

    def stop(self, span: Span) -> Form:
        return self.offset[span.region] + Form.extent(span.region) - span.back


type _Found = dict[AlignmentError, None]


def _scalar(axes: _Axes, vector: str, e: Expr, in_seed: bool, found: _Found) -> None:
    """A scalar equation or a seed: region vectors only through a reduction, no lags."""
    match e:
        case Literal() | At():
            pass
        case Ref(name):
            if isinstance(axes.shapes.get(name), Span):
                if in_seed:
                    found[SeedNotScalar(vector, name)] = None
                else:
                    found[Misaligned(vector, name, "scalar")] = None
        case Last(name) | First(name):
            if isinstance(axes.shapes.get(name), Scalar):
                found[ReductionOfAScalar(vector, name)] = None
        case Neg(operand):
            _scalar(axes, vector, operand, in_seed, found)
        case Binary(_, left, right):
            _scalar(axes, vector, left, in_seed, found)
            _scalar(axes, vector, right, in_seed, found)
        case Lag(body, seed):
            found[LagOffAxis(vector)] = None
            _scalar(axes, vector, body, in_seed, found)
            if seed is not None:
                _scalar(axes, vector, seed, True, found)


def _vector(
    axes: _Axes,
    vector: str,
    target: Span,
    e: Expr,
    unseeded: int,
    seeded: int,
    found: _Found,
) -> None:
    """A region equation: ``e`` is asked for [start - unseeded, stop - unseeded - seeded)."""
    region = target.region
    axis = axes.axis_of[region]
    start, stop = axes.start(target), axes.stop(target)
    # Under `seeded` seeded lags, `e` is asked for anything only when the target has more
    # than `seeded` elements: the one condition that raises a minimum.
    within = dict(axes.minimum)
    within[region] = max(within[region], target.front + target.back + seeded + 1)
    match e:
        case Literal() | At():
            pass
        case Ref(name):
            leaf = axes.placed(name)
            if leaf is None:
                return
            if axes.axis_of[leaf.region] != axis:
                found[Misaligned(vector, name, "axis")] = None
                return
            if not (start - unseeded - axes.start(leaf)).nonnegative(within):
                found[Misaligned(vector, name, "before")] = None
            if not (axes.stop(leaf) - stop + unseeded + seeded).nonnegative(within):
                found[Misaligned(vector, name, "after")] = None
        case Last(name) | First(name):
            if isinstance(axes.shapes.get(name), Scalar):
                found[ReductionOfAScalar(vector, name)] = None
        case Neg(operand):
            _vector(axes, vector, target, operand, unseeded, seeded, found)
        case Binary(_, left, right):
            _vector(axes, vector, target, left, unseeded, seeded, found)
            _vector(axes, vector, target, right, unseeded, seeded, found)
        case Lag(body, seed):
            if seed is None:
                if not (start - unseeded - 1).nonnegative(within):
                    found[LagBeforeStart(vector, axis)] = None
                _vector(axes, vector, target, body, unseeded + 1, seeded, found)
            else:
                _scalar(axes, vector, seed, True, found)
                _vector(axes, vector, target, body, unseeded, seeded + 1, found)


def align(
    axes: tuple[Axis, ...],
    shapes: Mapping[str, Shape],
    equations: tuple[Equation, ...],
) -> tuple[AlignmentError, ...]:
    """Every alignment error in the equations, each reported once.

    Names and regions that are not declared or not placed are skipped here: the
    construction checks report them.
    """
    axis_of: dict[str, str] = {}
    offset: dict[str, Form] = {}
    for axis in axes:
        before = ZERO
        for region in axis.regions:
            axis_of.setdefault(region, axis.name)
            offset.setdefault(region, before)
            before = before + Form.extent(region)
    placement = _Axes(shapes, axis_of, offset, minimum_extents(axes, shapes))
    found: _Found = {}
    for equation in equations:
        vector = equation.name
        target = shapes.get(vector)
        if isinstance(target, Scalar):
            _scalar(placement, vector, equation.expression, False, found)
            continue
        span = placement.placed(vector)
        if span is not None:
            _vector(placement, vector, span, equation.expression, 0, 0, found)
    return tuple(found)
