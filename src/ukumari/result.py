"""A value or an error, with the meaning of Rust's ``Result``.

An expected failure is returned as an ``Err`` rather than raised, so a caller sees it in
the type and cannot forget it. A bug still raises.

>>> def parse(text: str) -> Result[int, str]:
...     return Ok(int(text)) if text.isdigit() else Err(f"not a number: {text!r}")
>>> parse("12").map(lambda n: n * 2)
Ok(value=24)
>>> parse("twelve").map(lambda n: n * 2)
Err(error="not a number: 'twelve'")

Taken apart with ``match``:

>>> match parse("7"):
...     case Ok(value):
...         print("got", value)
...     case Err(error):
...         print("failed:", error)
got 7
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Never

type Result[T, E] = Ok[T] | Err[E]


class UnwrapError(Exception):
    """Raised by unwrapping the variant a result is not.

    Its message is the error's ``str``. A tuple of errors, as ``partition_result``
    gathers them, is joined with ``"; "`` rather than shown as a repr.
    """


def _describe(error: object) -> str:
    match error:
        case tuple():
            return "; ".join(str(each) for each in error)
        case _:
            return str(error)


@dataclass(frozen=True, slots=True)
class Ok[T]:
    """A success, holding its value.

    The methods that act only on an error take a callable of ``Never``, so that a type
    checker accepts them on either variant of a ``Result``.

    >>> Ok(2).and_then(lambda n: Ok(n + 1))
    Ok(value=3)
    >>> Ok(2).map_err(str.upper)
    Ok(value=2)
    >>> Ok(2).unwrap(), Ok(2).expect("reading the count")
    (2, 2)
    >>> try:
    ...     Ok(2).unwrap_err()
    ... except UnwrapError as error:
    ...     print(error)
    expected an error, found the value 2
    """

    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def map[U](self, f: Callable[[T], U]) -> Ok[U]:
        return Ok(f(self.value))

    def map_err(self, f: Callable[[Never], object]) -> Ok[T]:
        return self

    def and_then[U, E](self, f: Callable[[T], Result[U, E]]) -> Result[U, E]:
        return f(self.value)

    def unwrap(self) -> T:
        return self.value

    def expect(self, message: str) -> T:
        return self.value

    def unwrap_err(self) -> Never:
        raise UnwrapError(f"expected an error, found the value {self.value!r}")


@dataclass(frozen=True, slots=True)
class Err[E]:
    """A failure, holding its error.

    The methods that act only on a value take a callable of ``Never``, so that a type
    checker accepts them on either variant of a ``Result``.

    >>> Err("disk full").and_then(lambda n: Ok(n + 1))
    Err(error='disk full')
    >>> Err("disk full").map_err(str.upper)
    Err(error='DISK FULL')
    >>> Err("disk full").unwrap_err()
    'disk full'
    >>> try:
    ...     Err("disk full").expect("saving the file")
    ... except UnwrapError as error:
    ...     print(error)
    saving the file: disk full
    >>> try:
    ...     Err(("no header", "row 3 is empty")).unwrap()
    ... except UnwrapError as error:
    ...     print(error)
    no header; row 3 is empty
    """

    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def map(self, f: Callable[[Never], object]) -> Err[E]:
        return self

    def map_err[F](self, f: Callable[[E], F]) -> Err[F]:
        return Err(f(self.error))

    def and_then(self, f: Callable[[Never], object]) -> Err[E]:
        return self

    def unwrap(self) -> Never:
        raise UnwrapError(_describe(self.error))

    def expect(self, message: str) -> Never:
        raise UnwrapError(f"{message}: {_describe(self.error)}")

    def unwrap_err(self) -> E:
        return self.error


def collect[T, E](results: Iterable[Result[T, E]]) -> Result[tuple[T, ...], E]:
    """Every value as a tuple, or the first error.

    It stops reading at that error, so later results are never computed.

    >>> collect([Ok(1), Ok(2)])
    Ok(value=(1, 2))
    >>> def noisy(n):
    ...     print("reading", n)
    ...     return Err(f"bad {n}") if n % 2 else Ok(n)
    >>> collect(noisy(n) for n in [2, 3, 5])
    reading 2
    reading 3
    Err(error='bad 3')
    """
    values: list[T] = []
    for result in results:
        match result:
            case Ok(value):
                values.append(value)
            case Err():
                return result
    return Ok(tuple(values))


def partition_result[T, E](
    results: Iterable[Result[T, E]],
) -> tuple[tuple[T, ...], tuple[E, ...]]:
    """Every value and every error, each as a tuple.

    This is how a pass reports every problem at once, rather than only the first.

    >>> partition_result([Ok(1), Err("bad 2"), Ok(3), Err("bad 4")])
    ((1, 3), ('bad 2', 'bad 4'))
    """
    values: list[T] = []
    errors: list[E] = []
    for result in results:
        match result:
            case Ok(value):
                values.append(value)
            case Err(error):
                errors.append(error)
    return tuple(values), tuple(errors)
