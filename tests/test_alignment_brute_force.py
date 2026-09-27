"""Alignment compared with a brute-force checker on random guarded models.

The real checker decides alignment with no extents at all, over linear forms. The checker
here knows nothing of forms: it tries every combination of small extents, works out
concretely which positions each leaf is asked for, and collects every error it sees. On a
box the symbolic answer is exact, so the two must agree on every model: the verdict and the
errors reported.
"""

import itertools
import random
from collections.abc import Mapping

from models import random_model

from ukumari.align import align
from ukumari.circuit import Equation
from ukumari.errors import (
    AlignmentError,
    LagBeforeStart,
    LagOffAxis,
    Misaligned,
    ReductionOfAScalar,
    SeedNotScalar,
)
from ukumari.expr import Binary, Expr, Lag, Last, Neg, Ref
from ukumari.guard import schedule
from ukumari.shape import Axis, Scalar, Shape, Span

MODELS = 1000
HEADROOM = 6  # extents tried above each region's minimum


def _scalar_ctx(
    shapes: Mapping[str, Shape],
    v: str,
    e: Expr,
    in_seed: bool,
    found: set[AlignmentError],
) -> None:
    match e:
        case Ref(name) if isinstance(shapes[name], Span):
            found.add(
                SeedNotScalar(v, name) if in_seed else Misaligned(v, name, "scalar")
            )
        case Last(name) if isinstance(shapes[name], Scalar):
            found.add(ReductionOfAScalar(v, name))
        case Neg(x):
            _scalar_ctx(shapes, v, x, in_seed, found)
        case Binary(_, left, right):
            _scalar_ctx(shapes, v, left, in_seed, found)
            _scalar_ctx(shapes, v, right, in_seed, found)
        case Lag(body, seed):
            found.add(LagOffAxis(v))
            _scalar_ctx(shapes, v, body, in_seed, found)
            if seed is not None:
                _scalar_ctx(shapes, v, seed, True, found)
        case _:
            pass


def _vector_ctx(
    shapes: Mapping[str, Shape],
    where: Mapping[str, tuple[str, int, int]],
    v: str,
    e: Expr,
    a: int,
    b: int,
    found: set[AlignmentError],
) -> None:
    """``e`` is asked for positions [a, b) of the axis ``v`` lies on."""
    if b <= a:
        return  # asked for nothing
    axis = where[v][0]
    match e:
        case Ref(name) if isinstance(shapes[name], Span):
            leaf_axis, first, stop = where[name]
            if leaf_axis != axis:
                found.add(Misaligned(v, name, "axis"))
                return
            if a < first:
                found.add(Misaligned(v, name, "before"))
            if b > stop:
                found.add(Misaligned(v, name, "after"))
        case Last(name) if isinstance(shapes[name], Scalar):
            found.add(ReductionOfAScalar(v, name))
        case Neg(x):
            _vector_ctx(shapes, where, v, x, a, b, found)
        case Binary(_, left, right):
            _vector_ctx(shapes, where, v, left, a, b, found)
            _vector_ctx(shapes, where, v, right, a, b, found)
        case Lag(body, None):
            if a - 1 < 0:
                found.add(LagBeforeStart(v, axis))
            _vector_ctx(shapes, where, v, body, a - 1, b - 1, found)
        case Lag(body, seed):
            assert seed is not None
            _scalar_ctx(shapes, v, seed, True, found)
            _vector_ctx(shapes, where, v, body, a, b - 1, found)
        case _:
            pass


def brute_force(
    axes: tuple[Axis, ...],
    shapes: Mapping[str, Shape],
    equations: tuple[Equation, ...],
) -> set[AlignmentError]:
    regions = [r for axis in axes for r in axis.regions]
    spans = [s for s in shapes.values() if isinstance(s, Span)]
    low = {
        r: max([1] + [s.front + s.back + 1 for s in spans if s.region == r])
        for r in regions
    }
    found: set[AlignmentError] = set()
    ranges = (range(low[r], low[r] + HEADROOM) for r in regions)
    for choice in itertools.product(*ranges):
        extent = dict(zip(regions, choice, strict=True))
        start_of: dict[str, tuple[str, int]] = {}
        for axis in axes:
            at = 0
            for r in axis.regions:
                start_of[r] = (axis.name, at)
                at += extent[r]
        where: dict[str, tuple[str, int, int]] = {}
        for name, shape in shapes.items():
            if isinstance(shape, Span):
                axis_name, begin = start_of[shape.region]
                stop = begin + extent[shape.region] - shape.back
                where[name] = (axis_name, begin + shape.front, stop)
        for eq in equations:
            if isinstance(shapes[eq.name], Scalar):
                _scalar_ctx(shapes, eq.name, eq.expression, False, found)
            else:
                _, a, b = where[eq.name]
                _vector_ctx(shapes, where, eq.name, eq.expression, a, b, found)
    return found


def test_alignment_agrees_with_brute_force_on_random_models() -> None:
    rng = random.Random(20260926)
    verdicts = {True: 0, False: 0}
    kinds: set[str] = set()
    for _ in range(MODELS):
        axes, shapes, equations = random_model(rng)
        guard_errors, _ = schedule(equations)
        assert guard_errors == (), "the generator makes guarded models only"
        symbolic = align(axes, shapes, equations)
        assert len(set(symbolic)) == len(symbolic), "each error is reported once"
        concrete = brute_force(axes, shapes, equations)
        assert set(symbolic) == concrete, (axes, shapes, equations)
        verdicts[not symbolic] += 1
        kinds |= {type(e).__name__ for e in symbolic}
        kinds |= {f"Misaligned.{e.side}" for e in symbolic if isinstance(e, Misaligned)}
    # The comparison means something only if both verdicts, and every kind, occur.
    assert verdicts[True] > 100 and verdicts[False] > 100, verdicts
    assert kinds >= {
        "LagBeforeStart",
        "LagOffAxis",
        "ReductionOfAScalar",
        "SeedNotScalar",
        "Misaligned.before",
        "Misaligned.after",
        "Misaligned.axis",
        "Misaligned.scalar",
    }, kinds
