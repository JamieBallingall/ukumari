"""The unroll, V to S: one node per operation, in topological order.

::

    inputs first; then, for each layer:
        its single values, in schedule order;
        for each axis, for t in 0 … extent − 1:
            for each vector in schedule order on that axis, if t is in its interval:
                cells[vector][t] = build(its equation written out at t)

``At(name, p)`` is a lookup of a cell already built: position-major order guarantees it
exists, since a lag reads an earlier position and a same-position reference reads a vector
the schedule put first.

Nodes are shared by structure (hash-consing): a node is a primitive and its operand ids, and
identical nodes are one node, so ``opening[1]`` is ``closing[0]``. Literals are the
exception: every occurrence is its own node, or an unrelated ``2`` would become a reference
to some other row that happens to hold ``2``. Every operand id is smaller than its
consumer's, so S is evaluated in one forward pass.

S carries no addresses: placement is the separate layout.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from ukumari.bind import Bound, Whole, Written, at_position
from ukumari.circuit import Kind
from ukumari.expr import At, Binary, Expr, Lag, Last, Literal, Neg, Ref, to_double


class Prim(StrEnum):
    NEG = "neg"
    ADD = "add"
    SUB = "sub"
    MUL = "mul"
    DIV = "div"
    MIN = "min"
    MAX = "max"


@dataclass(frozen=True, slots=True)
class Const:
    """A literal, as the double it computes as. Never shared."""

    value: float


@dataclass(frozen=True, slots=True)
class Element:
    """One value of an input: position ``index`` within the input's own values."""

    name: str
    index: int


@dataclass(frozen=True, slots=True)
class Operation:
    prim: Prim
    operands: tuple[int, ...]


type Node = Const | Element | Operation

type Cell = tuple[str, int | None]
"""A declared name and an absolute position on its axis, or None for a single value."""


@dataclass(frozen=True, slots=True)
class Straight:
    """S: nodes in topological order, and which node every cell holds.

    ``cells`` is in unroll order. A node's origin is the first cell, in that order, whose
    root is that node; a node built only inside a larger expression has none.
    """

    nodes: tuple[Node, ...]
    cells: Mapping[Cell, int]
    origins: Mapping[int, Cell]


def unroll(bound: Bound) -> Straight:
    """S, from V. It cannot fail on a checked, bound model, so it returns S itself."""
    circuit = bound.circuit
    shapes = circuit.shapes()
    nodes: list[Node] = []
    shared: dict[Operation, int] = {}
    cells: dict[Cell, int] = {}
    origins: dict[int, Cell] = {}

    def new(node: Node) -> int:
        nodes.append(node)
        return len(nodes) - 1

    def intern(node: Operation) -> int:
        if node not in shared:
            shared[node] = new(node)
        return shared[node]

    def hold(cell: Cell, node: int) -> None:
        cells[cell] = node
        origins.setdefault(node, cell)

    def last_cell(name: str) -> Cell:
        interval = bound.intervals[name]
        assert interval is not None, "a checked model never reduces a single value"
        return (name, interval.stop - 1)

    def build(e: Expr) -> int:
        match e:
            case Literal(value):
                return new(Const(to_double(value)))
            case Ref(name):
                return cells[(name, None)]
            case At(name, position):
                return cells[(name, position)]
            case Last(name):
                return cells[last_cell(name)]
            case Neg(operand):
                return intern(Operation(Prim.NEG, (build(operand),)))
            case Binary(op, left, right):
                operands = (build(left), build(right))
                return intern(Operation(Prim(op.value), operands))
            case Lag():
                raise AssertionError("an equation is written out before it is built")

    for d in circuit.declarations:
        if d.kind is Kind.INPUT:
            interval = bound.intervals[d.name]
            if interval is None:
                hold((d.name, None), new(Element(d.name, 0)))
            else:
                for index, t in enumerate(range(interval.start, interval.stop)):
                    hold((d.name, t), new(Element(d.name, index)))

    def written(name: str, t: int) -> Expr:
        match bound.equations[name]:
            case Written(positions):
                interval = bound.intervals[name]
                assert interval is not None
                return positions[t - interval.start]
            case Whole(expression):
                interval = bound.intervals[name]
                assert interval is not None
                return at_position(expression, t, interval.start, shapes)

    for layer in circuit.schedule:
        order = [name for c in layer.components for name in c.members]
        for name in order:
            if bound.intervals[name] is None:
                match bound.equations[name]:
                    case Whole(expression):
                        hold((name, None), build(expression))
                    case Written():
                        raise AssertionError("a single value is never written out")
        for axis in circuit.axes:
            on_axis = [
                (name, interval)
                for name in order
                if (interval := bound.intervals[name]) is not None
                and interval.axis == axis.name
            ]
            extent = sum(bound.extents[region] for region in axis.regions)
            for t in range(extent):
                for name, interval in on_axis:
                    if interval.start <= t < interval.stop:
                        hold((name, t), build(written(name, t)))
    return Straight(tuple(nodes), cells, origins)
