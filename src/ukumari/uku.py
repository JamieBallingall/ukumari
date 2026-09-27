"""``.uku``: L as JSON (α, second half).

::

    {"format": "ukumari.model", "version": 1,
     "axes":         [{"name": ..., "regions": [...]}, ...],
     "declarations": [{"name": ..., "kind": "input" | "vector", "shape": ...}, ...],
     "equations":    [{"name": ..., "expression": ...}, ...]}

- Declarations keep their order, which the layout reads; equations keep the order they were
  defined in, separately, because the schedule breaks ties by it.
- A shape is ``"scalar"`` or ``{"region": …, "front": n, "back": n}``.
- An expression is an object tagged by ``"op"``: ``literal``, ``name``, ``last``, ``neg``,
  ``add``, ``sub``, ``mul``, ``div``, ``min``, ``max`` or ``lag``. A ``lag`` has a ``body``
  and, when seeded, a ``seed``.
- A literal is a string holding a rational, such as ``"1/10"``, because a JSON number is a
  double. A reference is a bare name, so a file cannot contradict its own declarations
  about what is an input.

Writing uses a fixed key order, one axis, declaration or equation per line, so a change to
a model shows as a readable diff. Reading produces an A, never an L: a file passes the
model gate just as a script does.
"""

import json
import re
from dataclasses import dataclass
from fractions import Fraction

from ukumari.check import check
from ukumari.circuit import Authored, Circuit, Declaration, Equation, Kind
from ukumari.errors import ModelError
from ukumari.expr import At, Binary, Expr, Lag, Last, Literal, Neg, Op, Ref
from ukumari.result import Err, Ok, Result
from ukumari.shape import Axis, Scalar, Shape, Span, scalar

FORMAT = "ukumari.model"
VERSION = 1

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]


@dataclass(frozen=True, slots=True)
class UkuError:
    """A problem in a ``.uku`` file, at a path such as ``equations[0].expression.op``."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


def _expression(e: Expr) -> dict[str, Json]:
    match e:
        case Literal(value):
            return {"op": "literal", "value": str(value)}
        case Ref(name):
            return {"op": "name", "name": name}
        case Last(name):
            return {"op": "last", "name": name}
        case Neg(operand):
            return {"op": "neg", "operand": _expression(operand)}
        case Binary(op, left, right):
            return {
                "op": str(op),
                "left": _expression(left),
                "right": _expression(right),
            }
        case Lag(body, seed):
            written: dict[str, Json] = {"op": "lag", "body": _expression(body)}
            if seed is not None:
                written["seed"] = _expression(seed)
            return written
        case At():
            raise AssertionError("a checked model holds no At")


def _shape(shape: Shape) -> Json:
    match shape:
        case Scalar():
            return "scalar"
        case Span(region, front, back):
            return {"region": region, "front": front, "back": back}


def write_uku(circuit: Circuit) -> str:
    """L as ``.uku`` text, ending with LF. Write it with ``newline=""``."""

    def line(item: Json) -> str:
        return json.dumps(item, ensure_ascii=False, separators=(", ", ": "))

    def block(key: str, items: list[Json]) -> str:
        if not items:
            return f'  "{key}": []'
        inner = ",\n".join(f"    {line(item)}" for item in items)
        return f'  "{key}": [\n{inner}\n  ]'

    axes: list[Json] = [
        {"name": a.name, "regions": list(a.regions)} for a in circuit.axes
    ]
    declarations: list[Json] = [
        {"name": d.name, "kind": str(d.kind), "shape": _shape(d.shape)}
        for d in circuit.declarations
    ]
    equations: list[Json] = [
        {"name": e.name, "expression": _expression(e.expression)}
        for e in circuit.equations
    ]
    body = ",\n".join(
        [
            f'  "format": {line(FORMAT)}',
            f'  "version": {VERSION}',
            block("axes", axes),
            block("declarations", declarations),
            block("equations", equations),
        ]
    )
    return "{\n" + body + "\n}\n"


_RATIONAL = re.compile(r"-?(0|[1-9][0-9]*)(/[1-9][0-9]*)?")
_BINARY = {str(op): op for op in Op}


class _Reader:
    """Reads a parsed file, collecting every problem with its path."""

    def __init__(self) -> None:
        self.errors: list[UkuError] = []

    def fail(self, path: str, message: str) -> None:
        self.errors.append(UkuError(path, message))

    def keys(
        self, path: str, item: dict[str, Json], required: set[str], optional=()
    ) -> bool:
        missing = sorted(required - item.keys())
        extra = sorted(item.keys() - required - set(optional))
        for key in missing:
            self.fail(path, f"missing {key!r}")
        for key in extra:
            self.fail(f"{path}.{key}", "not expected here")
        return not missing

    def name(self, path: str, value: Json) -> str | None:
        if isinstance(value, str) and value:
            return value
        self.fail(path, f"must be a non-empty string, not {json.dumps(value)}")
        return None

    def count(self, path: str, value: Json) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        self.fail(path, f"must be a whole number from 0, not {json.dumps(value)}")
        return None

    def items(self, path: str, value: Json) -> list[Json]:
        if isinstance(value, list):
            return value
        self.fail(path, "must be a list")
        return []

    def object(self, path: str, value: Json) -> dict[str, Json] | None:
        if isinstance(value, dict):
            return value
        self.fail(path, "must be an object")
        return None

    def shape(self, path: str, value: Json) -> Shape | None:
        if value == "scalar":
            return scalar
        item = self.object(path, value) if not isinstance(value, str) else None
        if item is None:
            if isinstance(value, str):
                self.fail(path, f'must be "scalar" or a span, not {json.dumps(value)}')
            return None
        if not self.keys(path, item, {"region", "front", "back"}):
            return None
        region = self.name(f"{path}.region", item["region"])
        front = self.count(f"{path}.front", item["front"])
        back = self.count(f"{path}.back", item["back"])
        if region is None or front is None or back is None:
            return None
        return Span(region, front, back)

    def expression(self, path: str, value: Json) -> Expr | None:
        item = self.object(path, value)
        if item is None:
            return None
        op = item.get("op")
        if not isinstance(op, str):
            self.fail(f"{path}.op", "must name an operation")
            return None
        match op:
            case "literal":
                if not self.keys(path, item, {"op", "value"}):
                    return None
                text = item["value"]
                if not isinstance(text, str) or not _RATIONAL.fullmatch(text):
                    self.fail(
                        f"{path}.value",
                        f'must be a string holding a rational such as "1/10", '
                        f"not {json.dumps(text)}",
                    )
                    return None
                return Literal(Fraction(text))
            case "name" | "last":
                if not self.keys(path, item, {"op", "name"}):
                    return None
                name = self.name(f"{path}.name", item["name"])
                if name is None:
                    return None
                return Ref(name) if op == "name" else Last(name)
            case "neg":
                if not self.keys(path, item, {"op", "operand"}):
                    return None
                operand = self.expression(f"{path}.operand", item["operand"])
                return None if operand is None else Neg(operand)
            case "lag":
                if not self.keys(path, item, {"op", "body"}, optional=("seed",)):
                    return None
                body = self.expression(f"{path}.body", item["body"])
                seed = None
                if "seed" in item:
                    seed = self.expression(f"{path}.seed", item["seed"])
                    if seed is None:
                        return None
                return None if body is None else Lag(body, seed)
            case _ if op in _BINARY:
                if not self.keys(path, item, {"op", "left", "right"}):
                    return None
                left = self.expression(f"{path}.left", item["left"])
                right = self.expression(f"{path}.right", item["right"])
                if left is None or right is None:
                    return None
                return Binary(_BINARY[op], left, right)
            case _:
                self.fail(f"{path}.op", f"unknown operation {json.dumps(op)}")
                return None

    def model(self, document: Json) -> Authored | None:
        top = self.object("", document)
        if top is None:
            return None
        required = {"format", "version", "axes", "declarations", "equations"}
        if not self.keys("", top, required):
            return None
        if top["format"] != FORMAT:
            self.fail("format", f"must be {json.dumps(FORMAT)}")
        version = top["version"]
        if not isinstance(version, int) or isinstance(version, bool) or version != 1:
            self.fail("version", f"must be {VERSION}, not {json.dumps(version)}")

        axes: list[Axis] = []
        for i, value in enumerate(self.items("axes", top["axes"])):
            path = f"axes[{i}]"
            item = self.object(path, value)
            if item is None or not self.keys(path, item, {"name", "regions"}):
                continue
            name = self.name(f"{path}.name", item["name"])
            regions = [
                self.name(f"{path}.regions[{j}]", r)
                for j, r in enumerate(self.items(f"{path}.regions", item["regions"]))
            ]
            if name is not None and None not in regions:
                axes.append(Axis(name, tuple(r for r in regions if r is not None)))

        declarations: list[Declaration] = []
        for i, value in enumerate(self.items("declarations", top["declarations"])):
            path = f"declarations[{i}]"
            item = self.object(path, value)
            if item is None or not self.keys(path, item, {"name", "kind", "shape"}):
                continue
            name = self.name(f"{path}.name", item["name"])
            kind = item["kind"]
            if kind not in ("input", "vector"):
                self.fail(
                    f"{path}.kind",
                    f'must be "input" or "vector", not {json.dumps(kind)}',
                )
            shape = self.shape(f"{path}.shape", item["shape"])
            if (
                name is not None
                and isinstance(kind, str)
                and kind in ("input", "vector")
                and shape is not None
            ):
                declarations.append(Declaration(name, Kind(kind), shape))

        equations: list[Equation] = []
        for i, value in enumerate(self.items("equations", top["equations"])):
            path = f"equations[{i}]"
            item = self.object(path, value)
            if item is None or not self.keys(path, item, {"name", "expression"}):
                continue
            name = self.name(f"{path}.name", item["name"])
            expression = self.expression(f"{path}.expression", item["expression"])
            if name is not None and expression is not None:
                equations.append(Equation(name, expression))

        regions = tuple(dict.fromkeys(r for axis in axes for r in axis.regions))
        return Authored(regions, tuple(axes), tuple(declarations), tuple(equations))


def read_uku(text: str) -> Result[Authored, tuple[UkuError, ...]]:
    """A, from ``.uku`` text, or every problem with the file's structure."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        return Err((UkuError("", f"not JSON: {error}"),))
    reader = _Reader()
    authored = reader.model(document)
    if reader.errors or authored is None:
        return Err(tuple(reader.errors))
    return Ok(authored)


def load_uku(text: str) -> Result[Circuit, tuple[UkuError | ModelError, ...]]:
    """L, from ``.uku`` text: read, then through the model gate."""
    match read_uku(text):
        case Err(errors):
            return Err(errors)
        case Ok(authored):
            match check(authored):
                case Err(model_errors):
                    return Err(model_errors)
                case Ok(circuit):
                    return Ok(circuit)
