"""Model errors: everything the model gate can find wrong with an authored model.

Each is a dataclass whose ``str`` names the vectors in the author's own terms. Names are
shown as Python string literals, so a name holding a quote or a newline cannot garble a
message.
"""

from dataclasses import dataclass
from typing import Literal as Choice


@dataclass(frozen=True, slots=True)
class DuplicateName:
    name: str

    def __str__(self) -> str:
        return f"{self.name!r} is declared more than once"


@dataclass(frozen=True, slots=True)
class Undefined:
    name: str

    def __str__(self) -> str:
        return f"{self.name!r} is declared but never defined"


@dataclass(frozen=True, slots=True)
class Redefined:
    name: str

    def __str__(self) -> str:
        return f"{self.name!r} is defined more than once"


@dataclass(frozen=True, slots=True)
class UnknownName:
    """A name that nothing declares. ``where`` is the equation mentioning it, if any."""

    name: str
    where: str | None

    def __str__(self) -> str:
        if self.where is None:
            return f"an equation defines {self.name!r}, which is not declared"
        return f"{self.where!r} refers to {self.name!r}, which is not declared"


@dataclass(frozen=True, slots=True)
class DefinedInput:
    name: str

    def __str__(self) -> str:
        return f"{self.name!r} is an input, so it is data and cannot be defined"


@dataclass(frozen=True, slots=True)
class DuplicateRegion:
    region: str

    def __str__(self) -> str:
        return f"region {self.region!r} is declared more than once"


@dataclass(frozen=True, slots=True)
class DuplicateAxis:
    axis: str

    def __str__(self) -> str:
        return f"axis {self.axis!r} is declared more than once"


@dataclass(frozen=True, slots=True)
class UnplacedRegion:
    region: str

    def __str__(self) -> str:
        return f"region {self.region!r} is on no axis"


@dataclass(frozen=True, slots=True)
class RegionOnTwoAxes:
    region: str
    axes: tuple[str, str]

    def __str__(self) -> str:
        first, second = self.axes
        return (
            f"region {self.region!r} is placed more than once, "
            f"on axis {first!r} and on axis {second!r}"
        )


@dataclass(frozen=True, slots=True)
class UnknownRegion:
    """A region that nothing declares. ``where`` names the axis or declaration using it."""

    region: str
    where: str

    def __str__(self) -> str:
        return f"{self.where} refers to region {self.region!r}, which is not declared"


@dataclass(frozen=True, slots=True)
class UnguardedCycle:
    """A cycle of references that no lag crosses, as a path back to its start."""

    cycle: tuple[str, ...]

    def __str__(self) -> str:
        path = " -> ".join(repr(name) for name in (*self.cycle, self.cycle[0]))
        return f"a cycle of references that no lag crosses: {path}"


@dataclass(frozen=True, slots=True)
class CircularReduction:
    vector: str
    source: str

    def __str__(self) -> str:
        return (
            f"{self.vector!r} reduces {self.source!r}, which depends on {self.vector!r}: "
            f"a reduction needs the whole of {self.source!r} first"
        )


type Side = Choice["before", "after", "axis", "scalar"]


@dataclass(frozen=True, slots=True)
class Misaligned:
    """A leaf that cannot supply a value everywhere its equation needs one.

    ``side`` says how: the equation reads positions ``before`` the leaf starts or ``after``
    it ends, reads a leaf on another ``axis``, or is a ``scalar`` equation reading a vector
    other than through a reduction.
    """

    vector: str
    leaf: str
    side: Side

    def __str__(self) -> str:
        match self.side:
            case "before":
                return (
                    f"{self.vector!r} reads {self.leaf!r} at a position "
                    f"before {self.leaf!r} starts"
                )
            case "after":
                return (
                    f"{self.vector!r} reads {self.leaf!r} at a position "
                    f"after {self.leaf!r} ends"
                )
            case "axis":
                return f"{self.vector!r} reads {self.leaf!r}, which is on another axis"
            case "scalar":
                return (
                    f"{self.vector!r} is a single value, so it can read the vector "
                    f"{self.leaf!r} only through a reduction such as last()"
                )


@dataclass(frozen=True, slots=True)
class LagOffAxis:
    vector: str

    def __str__(self) -> str:
        return (
            f"{self.vector!r} has a lag where a single value is needed (a scalar "
            "equation or a seed), and a single value has no previous position"
        )


@dataclass(frozen=True, slots=True)
class LagBeforeStart:
    vector: str
    axis: str

    def __str__(self) -> str:
        return (
            f"{self.vector!r} has a lag with no seed that can reach before the start "
            f"of axis {self.axis!r}: give it a seed, or trim the front of the span "
            f"{self.vector!r} is defined on"
        )


@dataclass(frozen=True, slots=True)
class ReductionOfAScalar:
    vector: str
    source: str

    def __str__(self) -> str:
        return (
            f"{self.vector!r} reduces {self.source!r}, which is already a single value"
        )


@dataclass(frozen=True, slots=True)
class SeedNotScalar:
    vector: str
    leaf: str

    def __str__(self) -> str:
        return (
            f"a seed in {self.vector!r} reads the vector {self.leaf!r}, but a seed must "
            "be a single value, such as last() of a vector"
        )


type ConstructionError = (
    DuplicateName
    | Undefined
    | Redefined
    | UnknownName
    | DefinedInput
    | DuplicateRegion
    | DuplicateAxis
    | UnplacedRegion
    | RegionOnTwoAxes
    | UnknownRegion
)
type GuardError = UnguardedCycle | CircularReduction
type AlignmentError = (
    Misaligned | LagOffAxis | LagBeforeStart | ReductionOfAScalar | SeedNotScalar
)
type ModelError = ConstructionError | GuardError | AlignmentError
