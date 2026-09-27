"""The expression tree: the signature of the language, and nothing else.

An expression is a union of frozen dataclasses. It carries no numbers beyond exact literals
and does no arithmetic: every interpretation (checking, computing, laying out, emitting)
walks the same tree.

Arithmetic on expressions builds bigger expressions, so a model reads like the algebra it
describes. A plain number on either side becomes a literal.

>>> x = Ref("x")
>>> x * 2 + 1
Binary(op=<Op.ADD: 'add'>, left=Binary(op=<Op.MUL: 'mul'>, left=Ref(name='x'), right=Literal(value=Fraction(2, 1))), right=Literal(value=Fraction(1, 1)))
>>> show(1 - x / 0.1)
'(1 - (x / 1/10))'
"""

import math
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction


class Op(StrEnum):
    """The binary operations. Subtraction and division are primitives, not derived."""

    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    MIN = "min"
    MAX = "max"


type Number = int | float | Fraction | Decimal


class Arith:
    """Arithmetic on anything that stands for an expression.

    Subclasses say which expression they stand for through ``expression``.
    """

    __slots__ = ()

    def expression(self) -> Expr:
        raise NotImplementedError

    def define(self, body: Arith | Number) -> None:
        # Only a declared vector can be defined. Reaching here means the script tried to
        # define something built from one, which is a bug in the script, not a model error.
        raise TypeError(
            "only a declared vector can be defined, not an expression built from one: "
            f"{show(self.expression())}"
        )

    def __add__(self, other: Arith | Number) -> Binary:
        return Binary(Op.ADD, self.expression(), to_expr(other))

    def __radd__(self, other: Number) -> Binary:
        return Binary(Op.ADD, to_expr(other), self.expression())

    def __sub__(self, other: Arith | Number) -> Binary:
        return Binary(Op.SUB, self.expression(), to_expr(other))

    def __rsub__(self, other: Number) -> Binary:
        return Binary(Op.SUB, to_expr(other), self.expression())

    def __mul__(self, other: Arith | Number) -> Binary:
        return Binary(Op.MUL, self.expression(), to_expr(other))

    def __rmul__(self, other: Number) -> Binary:
        return Binary(Op.MUL, to_expr(other), self.expression())

    def __truediv__(self, other: Arith | Number) -> Binary:
        return Binary(Op.DIV, self.expression(), to_expr(other))

    def __rtruediv__(self, other: Number) -> Binary:
        return Binary(Op.DIV, to_expr(other), self.expression())

    def __neg__(self) -> Neg:
        return Neg(self.expression())


@dataclass(frozen=True, slots=True)
class Literal(Arith):
    """An exact rational constant. It becomes a double only when it is computed."""

    value: Fraction

    def expression(self) -> Expr:
        return self


@dataclass(frozen=True, slots=True)
class Ref(Arith):
    """A reference to a declared vector or input, by name."""

    name: str

    def expression(self) -> Expr:
        return self


@dataclass(frozen=True, slots=True)
class Last(Arith):
    """The final element of a declared vector or input: a reduction to a single value."""

    name: str

    def expression(self) -> Expr:
        return self


@dataclass(frozen=True, slots=True)
class At(Arith):
    """One position of a vector, by absolute position on its axis.

    ``At`` appears only once a model is bound to data: binding writes each lag out as the
    position it reads. A checked model (L) never contains one.
    """

    name: str
    position: int

    def expression(self) -> Expr:
        return self


@dataclass(frozen=True, slots=True)
class Neg(Arith):
    """Negation, a primitive: ``-a`` and ``0 - a`` differ on signed zero."""

    operand: Expr

    def expression(self) -> Expr:
        return self


@dataclass(frozen=True, slots=True)
class Binary(Arith):
    op: Op
    left: Expr
    right: Expr

    def expression(self) -> Expr:
        return self


@dataclass(frozen=True, slots=True)
class Lag(Arith):
    """The previous position along the axis; ``seed`` supplies the first, if given."""

    body: Expr
    seed: Expr | None

    def expression(self) -> Expr:
        return self


type Expr = Literal | Ref | Last | At | Neg | Binary | Lag


def to_fraction(value: Number) -> Fraction:
    """A number as an exact rational: a float is read as what the author typed.

    >>> to_fraction(0.1), to_fraction(3), to_fraction(Decimal("2.50"))
    (Fraction(1, 10), Fraction(3, 1), Fraction(5, 2))
    >>> to_fraction(float("inf"))
    Traceback (most recent call last):
    ...
    ValueError: a literal must be finite, not inf
    """
    match value:
        case bool():
            raise TypeError(f"a literal must be a number, not {value!r}")
        case int() | Fraction():
            return Fraction(value)
        case float():
            if not math.isfinite(value):
                raise ValueError(f"a literal must be finite, not {value!r}")
            return Fraction(repr(value))
        case Decimal():
            if not value.is_finite():
                raise ValueError(f"a literal must be finite, not {value}")
            return Fraction(value)
        case _:
            raise TypeError(f"a literal must be a number, not {value!r}")


def to_expr(value: Arith | Number) -> Expr:
    """An operand as an expression: a plain number becomes a literal."""
    if isinstance(value, Arith):
        return value.expression()
    return Literal(to_fraction(value))


def to_double(value: Fraction) -> float:
    """A literal as the double it computes as; one too large for a double is the error value.

    >>> to_double(Fraction(1, 10))
    0.1
    >>> to_double(Fraction(10**400))
    nan
    """
    try:
        return float(value)
    except OverflowError:
        return math.nan


def walk(expr: Expr) -> Iterator[Expr]:
    """Every node of an expression, parents before children, left before right."""
    yield expr
    match expr:
        case Literal() | Ref() | Last() | At():
            pass
        case Neg(operand):
            yield from walk(operand)
        case Binary(_, left, right):
            yield from walk(left)
            yield from walk(right)
        case Lag(body, seed):
            yield from walk(body)
            if seed is not None:
                yield from walk(seed)


_SYMBOLS = {Op.ADD: "+", Op.SUB: "-", Op.MUL: "*", Op.DIV: "/"}


def show(expr: Expr) -> str:
    """A compact, fully parenthesised rendering, for messages and debugging.

    >>> show(Lag(Ref("x"), Last("x_actual")) * (1 + Ref("g")))
    '(lag(x, seed=last(x_actual)) * (1 + g))'
    """
    match expr:
        case Literal(value):
            return str(value)
        case Ref(name):
            return name
        case Last(name):
            return f"last({name})"
        case At(name, position):
            return f"{name}[{position}]"
        case Neg(operand):
            return f"-{show(operand)}"
        case Binary(op, left, right) if op in _SYMBOLS:
            return f"({show(left)} {_SYMBOLS[op]} {show(right)})"
        case Binary(op, left, right):
            return f"{op}({show(left)}, {show(right)})"
        case Lag(body, seed):
            if seed is None:
                return f"lag({show(body)})"
            return f"lag({show(body)}, seed={show(seed)})"
