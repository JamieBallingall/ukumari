"""Shapes: where a vector lives, never how long it is.

An axis is an ordered list of regions. A region's extent (its length) comes from the data. A
declared shape is a span (a region with trims at either end) or ``scalar``. Once extents are
known, a span resolves to an absolute interval ``[start, stop)`` on its axis.

>>> history = Span("history")
>>> history[1:], history[:-1], history[1:][:-2]
(Span(region='history', front=1, back=0), Span(region='history', front=0, back=1), Span(region='history', front=1, back=2))
>>> axes = (Axis("year", ("history", "forecast")),)
>>> regions = place(axes, {"history": 3, "forecast": 5})
>>> regions["forecast"]
Interval(axis='year', start=3, stop=8)
>>> resolve(history[1:], regions)
Interval(axis='year', start=1, stop=3)
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scalar:
    """The shape of a single value, which broadcasts wherever it is used."""

    def __repr__(self) -> str:
        return "scalar"


scalar = Scalar()


@dataclass(frozen=True, slots=True)
class Span:
    """A region, with ``front`` positions dropped at its start and ``back`` at its end.

    Only the ends can be trimmed: ``region[1:]``, ``region[:-1]`` and ``region[1:-1]``.

    >>> Span("r")[2:-1]
    Span(region='r', front=2, back=1)
    >>> Span("r")[1:3]
    Traceback (most recent call last):
    ...
    TypeError: only the ends of a region can be trimmed: use region[f:] and region[:-b]
    """

    region: str
    front: int = 0
    back: int = 0

    def __getitem__(self, key: slice) -> Span:
        if not isinstance(key, slice) or key.step is not None:
            raise TypeError("a region is trimmed with a slice such as region[1:]")
        start = 0 if key.start is None else key.start
        stop = 0 if key.stop is None else key.stop
        valid = (
            isinstance(start, int)
            and isinstance(stop, int)
            and not isinstance(start, bool)
            and not isinstance(stop, bool)
            and start >= 0
            and (key.stop is None or stop < 0)
        )
        if not valid:
            raise TypeError(
                "only the ends of a region can be trimmed: use region[f:] and region[:-b]"
            )
        return Span(self.region, self.front + start, self.back - stop)


type Shape = Scalar | Span


@dataclass(frozen=True, slots=True)
class Axis:
    """Regions in order along one axis. A region is on exactly one axis."""

    name: str
    regions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Interval:
    """Absolute positions ``[start, stop)`` on an axis."""

    axis: str
    start: int
    stop: int

    @property
    def length(self) -> int:
        return self.stop - self.start

    def contains(self, other: Interval) -> bool:
        """Whether every position of ``other`` is a position of this interval.

        An empty interval asks for nothing, so every interval on any axis contains it.

        >>> Interval("t", 0, 5).contains(Interval("t", 1, 3))
        True
        >>> Interval("t", 0, 5).contains(Interval("t", -1, 3))
        False
        >>> Interval("t", 0, 5).contains(Interval("t", 7, 7))
        True
        """
        if other.stop <= other.start:
            return True
        return (
            self.axis == other.axis
            and self.start <= other.start
            and other.stop <= self.stop
        )

    def shift(self, by: int) -> Interval:
        """The same interval, ``by`` positions later (earlier when negative)."""
        return Interval(self.axis, self.start + by, self.stop + by)


def place(axes: tuple[Axis, ...], extents: Mapping[str, int]) -> dict[str, Interval]:
    """Every region's interval, from the extents of the regions along each axis."""
    placed: dict[str, Interval] = {}
    for axis in axes:
        start = 0
        for region in axis.regions:
            stop = start + extents[region]
            placed[region] = Interval(axis.name, start, stop)
            start = stop
    return placed


def resolve(span: Span, regions: Mapping[str, Interval]) -> Interval:
    """The absolute interval a span covers, once its region is placed."""
    whole = regions[span.region]
    return Interval(whole.axis, whole.start + span.front, whole.stop - span.back)
