"""The two model graphs as data: A, what an author wrote, and L, a model that passed the gate.

Both are frozen. A may be wrong in any way the gate can report. Holding an L means every
later step succeeds for any data that binds.
"""

from dataclasses import dataclass
from enum import StrEnum

from ukumari.expr import Expr
from ukumari.shape import Axis, Scalar, Shape, Span


class Kind(StrEnum):
    INPUT = "input"
    VECTOR = "vector"


@dataclass(frozen=True, slots=True)
class Declaration:
    name: str
    kind: Kind
    shape: Shape


@dataclass(frozen=True, slots=True)
class Equation:
    name: str
    expression: Expr


@dataclass(frozen=True, slots=True)
class Authored:
    """A: the model as written, before any check.

    Declarations keep their order, which the layout reads. Equations keep the order they
    were defined in, which breaks ties in the schedule.
    """

    regions: tuple[str, ...]
    axes: tuple[Axis, ...]
    declarations: tuple[Declaration, ...]
    equations: tuple[Equation, ...]


@dataclass(frozen=True, slots=True)
class Component:
    """Vectors computed together, in the order they are computed at each position.

    A recurrent component has a lag on a cycle through it, so it is computed position by
    position. Any other component is a single vector, computed whole.
    """

    members: tuple[str, ...]
    recurrent: bool


@dataclass(frozen=True, slots=True)
class Layer:
    """Components in evaluation order. A reduction reads only from an earlier layer."""

    components: tuple[Component, ...]


@dataclass(frozen=True, slots=True)
class Circuit:
    """L: a model that has passed every check, with its schedule."""

    axes: tuple[Axis, ...]
    declarations: tuple[Declaration, ...]
    equations: tuple[Equation, ...]
    schedule: tuple[Layer, ...]

    def shapes(self) -> dict[str, Shape]:
        return {d.name: d.shape for d in self.declarations}

    def inputs(self) -> tuple[Declaration, ...]:
        return tuple(d for d in self.declarations if d.kind is Kind.INPUT)

    def vectors(self) -> tuple[Declaration, ...]:
        return tuple(d for d in self.declarations if d.kind is Kind.VECTOR)

    def definitions(self) -> dict[str, Expr]:
        return {e.name: e.expression for e in self.equations}

    def axis_of(self, name: str) -> str | None:
        """The axis a declared name lies on, or None for a single value."""
        match self.shapes()[name]:
            case Scalar():
                return None
            case Span(region):
                for axis in self.axes:
                    if region in axis.regions:
                        return axis.name
                raise AssertionError(f"region {region!r} is on no axis")
