"""The authoring surface: declare, then define.

Python cannot express a cyclic definition, so every vector is named first and defined
afterwards, which is what lets a recurrence refer to itself.

>>> m = Model()
>>> period = m.region("period")
>>> m.axis("month", period)
>>> scheduled = m.input("scheduled", period)
>>> opening, payment, closing = m.vectors(period, "opening", "payment", "closing")
>>> opening.define(lag(closing, seed=100))
>>> payment.define(minimum(scheduled, opening))
>>> closing.define(opening - payment)
>>> m.build().is_ok()
True

A model says where each vector lives, never how long it is: lengths arrive with the data.
"""

from ukumari.circuit import Authored, Circuit, Declaration, Equation, Kind
from ukumari.errors import ModelError
from ukumari.expr import (
    Arith,
    At,
    Binary,
    Lag,
    Last,
    Literal,
    Number,
    Op,
    Ref,
    to_expr,
    to_fraction,
    walk,
)
from ukumari.result import Result
from ukumari.shape import Axis, Scalar, Shape, Span


class Declared(Arith):
    """A declared vector or input: usable in expressions, and definable exactly once."""

    __slots__ = ("_model", "kind", "name", "shape")

    def __init__(self, model: Model, name: str, kind: Kind, shape: Shape) -> None:
        self._model = model
        self.name = name
        self.kind = kind
        self.shape = shape

    def expression(self) -> Ref:
        return Ref(self.name)

    def define(self, body: Arith | Number) -> None:
        expression = to_expr(body)
        if any(isinstance(node, At) for node in walk(expression)):
            raise TypeError(
                "a model's equations cannot hold At, which only binding makes"
            )
        self._model._equations.append(Equation(self.name, expression))

    def __repr__(self) -> str:
        return f"<{self.kind} {self.name!r}: {self.shape!r}>"


class Model:
    """The one mutable object. It exists only until ``build()`` returns a frozen L."""

    def __init__(self) -> None:
        self._regions: list[str] = []
        self._axes: list[Axis] = []
        self._declarations: list[Declaration] = []
        self._equations: list[Equation] = []

    def region(self, name: str) -> Span:
        """Declare a region, returning the span over all of it."""
        _check_name(name, "a region")
        self._regions.append(name)
        return Span(name)

    def axis(self, name: str, *regions: Span) -> None:
        """Order regions along an axis. A region is on exactly one axis."""
        _check_name(name, "an axis")
        for region in regions:
            if not isinstance(region, Span) or region.front or region.back:
                raise TypeError(f"an axis orders whole regions, not {region!r}")
        self._axes.append(Axis(name, tuple(r.region for r in regions)))

    def input(self, name: str, shape: Shape) -> Declared:
        """Declare data: every number that could change between runs arrives this way."""
        return self._declare(name, Kind.INPUT, shape)

    def vector(self, name: str, shape: Shape) -> Declared:
        """Declare a computed vector, to be defined exactly once."""
        return self._declare(name, Kind.VECTOR, shape)

    def vectors(self, shape: Shape, *names: str) -> tuple[Declared, ...]:
        """Declare several computed vectors of one shape."""
        return tuple(self._declare(name, Kind.VECTOR, shape) for name in names)

    def literal(self, value: Number) -> Literal:
        """A constant, held exactly: ``0.1`` is ``1/10``."""
        return Literal(to_fraction(value))

    def authored(self) -> Authored:
        """A: the model as written so far."""
        return Authored(
            regions=tuple(self._regions),
            axes=tuple(self._axes),
            declarations=tuple(self._declarations),
            equations=tuple(self._equations),
        )

    def build(self) -> Result[Circuit, tuple[ModelError, ...]]:
        """The model gate: an L, or every error in the model at once."""
        from ukumari.check import check

        return check(self.authored())

    def _declare(self, name: str, kind: Kind, shape: Shape) -> Declared:
        _check_name(name, f"an {kind}" if kind is Kind.INPUT else f"a {kind}")
        if not isinstance(shape, Scalar | Span):
            raise TypeError(f"a shape is a span or scalar, not {shape!r}")
        self._declarations.append(Declaration(name, kind, shape))
        return Declared(self, name, kind, shape)


def _check_name(name: object, what: str) -> None:
    if not isinstance(name, str) or not name:
        raise TypeError(f"the name of {what} must be a non-empty string, not {name!r}")


def lag(v: Arith | Number, seed: Arith | Number | None = None) -> Lag:
    """The previous position along the axis.

    With a seed, the first position asked for is the seed. Without one, every position
    reads the one before, so ``v`` must reach back one position further. Omitting the seed
    is not seeding with zero.
    """
    return Lag(to_expr(v), None if seed is None else to_expr(seed))


def last(v: Declared | Ref) -> Last:
    """The final element of a declared vector or input, as a single value."""
    match v:
        case Declared(name=name) | Ref(name=name):
            return Last(name)
        case _:
            raise TypeError(f"last() takes a declared vector or input, not {v!r}")


def minimum(a: Arith | Number, b: Arith | Number) -> Binary:
    """The smaller of two values; either being an error makes the result an error."""
    return Binary(Op.MIN, to_expr(a), to_expr(b))


def maximum(a: Arith | Number, b: Arith | Number) -> Binary:
    """The larger of two values; either being an error makes the result an error."""
    return Binary(Op.MAX, to_expr(a), to_expr(b))
