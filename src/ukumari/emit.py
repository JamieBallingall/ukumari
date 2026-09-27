"""β₃: emit P, a standalone NumPy program that computes a model at any length.

The program's contract is ``run(inputs, extents=None, outputs=None)``. ``inputs`` maps
each input name to an array of shape ``(scenarios, values)``; an input with one scenario is
used for every scenario, and a one-dimensional array is one scenario. The result maps each
requested output to ``(scenarios, positions)``; ``outputs=None`` requests every output.
``INPUTS`` and ``OUTPUTS`` name what it expects and gives.

It runs in three stages: its own data gate, which raises one ``ValueError`` naming every
problem; placement of the regions from the extents; and evaluation, layer by layer. A vector
outside every component is one operation over a slice of the row; a recurrent component is
a loop over positions in schedule order. It computes only what the requested outputs need,
and drops each intermediate after its last reader.

**No text from a model ever becomes code.** Identifiers are generated (``_v[7]``); names
appear only as ``repr`` string literals; numbers only as the ``repr`` of a float, with NaN
spelled out. A ``.uku`` file from someone else becomes code the moment its P runs.
"""

import math
from pathlib import Path
from types import ModuleType

from ukumari.bind import axis_table, declaration_table
from ukumari.circuit import Circuit, Component, Kind
from ukumari.expr import (
    At,
    Binary,
    Expr,
    First,
    Lag,
    Last,
    Literal,
    Neg,
    Op,
    Ref,
    to_double,
    walk,
)
from ukumari.shape import Scalar

_HELPERS = {
    Op.ADD: "_add",
    Op.SUB: "_sub",
    Op.MUL: "_mul",
    Op.DIV: "_div",
    Op.MIN: "_min",
    Op.MAX: "_max",
}


def _number(value: float) -> str:
    if math.isnan(value):
        return "float('nan')"
    if math.isinf(value):
        return "float('inf')" if value > 0 else "float('-inf')"
    return repr(value)


type _Position = tuple[str, int]
"""A position in generated code: a variable holding an absolute position, and an offset."""


def _position(p: _Position) -> str:
    base, offset = p
    if offset == 0:
        return base
    return f"{base} - {-offset}" if offset < 0 else f"{base} + {offset}"


def _shifted(p: _Position, by: int) -> _Position:
    return p[0], p[1] + by


class _Writer:
    """Code for expressions, given the index of every declared name.

    Declaration ``i`` computes into ``_v[i]``, and its interval is ``[s{i}, e{i})``.
    """

    def __init__(self, circuit: Circuit) -> None:
        self.index = {d.name: i for i, d in enumerate(circuit.declarations)}
        self.scalar = {
            d.name for d in circuit.declarations if isinstance(d.shape, Scalar)
        }

    def whole(self, e: Expr, a: _Position, b: _Position) -> str:
        """Code for ``e`` over absolute positions ``[a, b)``, one column per position."""
        match e:
            case Literal(value):
                return _number(to_double(value))
            case Ref(name) if name in self.scalar:
                return f"_v[{self.index[name]}]"
            case Ref(name):
                i = self.index[name]
                return (
                    f"_columns(_v[{i}], {_position(a)} - s{i}, {_position(b)} - s{i})"
                )
            case Last(name):
                return f"_v[{self.index[name]}][:, -1:]"
            case First(name):
                return f"_v[{self.index[name]}][:, :1]"
            case Neg(operand):
                return f"_neg({self.whole(operand, a, b)})"
            case Binary(op, left, right):
                return f"{_HELPERS[op]}({self.whole(left, a, b)}, {self.whole(right, a, b)})"
            case Lag(body, None):
                return self.whole(body, _shifted(a, -1), _shifted(b, -1))
            case Lag(body, seed):
                assert seed is not None
                width = _position((f"{b[0]} - {a[0]}", b[1] - a[1]))
                body_code = self.whole(body, a, _shifted(b, -1))
                return f"_lag({self.single(seed)}, {body_code}, _n, {width})"
            case At():
                raise AssertionError("a checked model holds no At")

    def at(self, e: Expr, t: _Position, first: _Position) -> str:
        """Code for ``e`` at the one position ``t``, first asked for at ``first``."""
        match e:
            case Literal(value):
                return _number(to_double(value))
            case Ref(name) if name in self.scalar:
                return f"_v[{self.index[name]}]"
            case Ref(name):
                i = self.index[name]
                after = _position(_shifted(t, 1))
                return f"_v[{i}][:, {_position(t)} - s{i}:{after} - s{i}]"
            case Last(name):
                return f"_v[{self.index[name]}][:, -1:]"
            case First(name):
                return f"_v[{self.index[name]}][:, :1]"
            case Neg(operand):
                return f"_neg({self.at(operand, t, first)})"
            case Binary(op, left, right):
                return (
                    f"{_HELPERS[op]}"
                    f"({self.at(left, t, first)}, {self.at(right, t, first)})"
                )
            case Lag(body, None):
                return self.at(body, _shifted(t, -1), _shifted(first, -1))
            case Lag(body, seed):
                assert seed is not None
                return (
                    f"({self.single(seed)} if {_position(t)} == {_position(first)} "
                    f"else {self.at(body, _shifted(t, -1), first)})"
                )
            case At():
                raise AssertionError("a checked model holds no At")

    def single(self, e: Expr) -> str:
        """Code for a single value: a scalar equation or a seed."""
        return self.whole(e, ("0", 0), ("1", 0))


def _reads(circuit: Circuit, component: Component) -> tuple[int, ...]:
    index = {d.name: i for i, d in enumerate(circuit.declarations)}
    definitions = circuit.definitions()
    found: list[int] = []
    for name in component.members:
        for node in walk(definitions[name]):
            match node:
                case Ref(used) | Last(used) | First(used):
                    if index[used] not in found and used not in component.members:
                        found.append(index[used])
                case _:
                    pass
    return tuple(found)


def _step(number: int, circuit: Circuit, component: Component, w: _Writer) -> str:
    definitions = circuit.definitions()
    members = [w.index[name] for name in component.members]
    # Names appear only as repr literals, here in a comment: repr never holds a line break.
    named = ", ".join(repr(name) for name in component.members)
    lines = [f"def _step{number}(_v, _p, _n):", f"    # {named}"]
    placed = sorted(
        i
        for i in {*members, *_reads(circuit, component)}
        if circuit.declarations[i].name not in w.scalar
    )
    lines += [f"    s{i}, e{i} = _p[{i}]" for i in placed]
    if not component.recurrent:
        (name,) = component.members
        i = w.index[name]
        if name in w.scalar:
            lines.append(f"    _v[{i}] = _fit({w.single(definitions[name])}, _n, 1)")
        else:
            code = w.whole(definitions[name], (f"s{i}", 0), (f"e{i}", 0))
            lines.append(f"    _v[{i}] = _fit({code}, _n, e{i} - s{i})")
        return "\n".join(lines)
    for i in members:
        lines.append(f"    _v[{i}] = _np.empty((_n, e{i} - s{i}))")
    starts = ", ".join(f"s{i}" for i in members)
    stops = ", ".join(f"e{i}" for i in members)
    if len(members) > 1:
        starts, stops = f"min({starts})", f"max({stops})"
    lines.append(f"    for _t in range({starts}, {stops}):")
    for name, i in zip(component.members, members, strict=True):
        code = w.at(definitions[name], ("_t", 0), (f"s{i}", 0))
        lines.append(f"        # {name!r}")
        lines.append(f"        if s{i} <= _t < e{i}:")
        lines.append(f"            _v[{i}][:, _t - s{i}:_t - s{i} + 1] = {code}")
    return "\n".join(lines)


def _runtime_source() -> str:
    return (Path(__file__).parent / "_runtime.py").read_text(encoding="utf-8")


def emit(circuit: Circuit) -> str:
    """P's source text. Running it needs NumPy and nothing else."""
    w = _Writer(circuit)
    runtime = _runtime_source()
    steps: list[str] = []
    table: list[str] = []
    number = 0
    for layer in circuit.schedule:
        for component in layer.components:
            steps.append(_step(number, circuit, component, w))
            writes = tuple(w.index[name] for name in component.members)
            reads = _reads(circuit, component)
            table.append(f"    (_step{number}, {reads!r}, {writes!r}),")
            number += 1
    inputs = tuple(d.name for d in circuit.declarations if d.kind is Kind.INPUT)
    outputs = tuple(d.name for d in circuit.declarations if d.kind is Kind.VECTOR)
    parts = [
        '"""A model as a NumPy program, generated by ukumari.',
        "",
        "Call run(inputs, extents=None, outputs=None). Do not edit: regenerate it.",
        '"""',
        "",
        "# ---- The runtime, copied from ukumari ----------------------------------------",
        "",
        runtime.split('"""', 2)[2].strip(),
        "",
        "",
        "# ---- The model ------------------------------------------------------------------",
        "",
        f"INPUTS = {inputs!r}",
        f"OUTPUTS = {outputs!r}",
        f"_DECLARATIONS = {declaration_table(circuit)!r}",
        f"_AXES = {axis_table(circuit.axes)!r}",
        "",
        "",
        "\n\n\n".join(steps),
        "",
        "",
        "_STEPS = (",
        *table,
        ")",
        "",
        "",
        "def run(inputs, extents=None, outputs=None):",
        '    """Compute the model: each requested output as (scenarios, positions)."""',
        "    return _run(_DECLARATIONS, _AXES, _STEPS, inputs, extents, outputs)",
        "",
    ]
    return "\n".join(parts)


def load(source: str) -> ModuleType:
    """P, ready to run.

    This is the one place ukumari executes generated code. That is acceptable: the author
    already runs arbitrary Python to build A, and no text from a model reaches the code
    except as a string literal or a float's ``repr``.
    """
    module = ModuleType("ukumari_program")
    exec(compile(source, "<ukumari program>", "exec"), module.__dict__)  # noqa: S102
    return module
