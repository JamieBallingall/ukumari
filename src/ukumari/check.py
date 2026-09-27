"""The model gate: A in, an L or every model error out.

Construction, guardedness and alignment are all checked, and their errors reported
together, so a circular reference never hides a misaligned leaf. Each check skips what an
earlier one has already reported as missing.
"""

from ukumari.align import align
from ukumari.circuit import Authored, Circuit, Declaration, Equation, Kind
from ukumari.errors import (
    DefinedInput,
    DuplicateAxis,
    DuplicateName,
    DuplicateRegion,
    ModelError,
    Redefined,
    RegionOnTwoAxes,
    Undefined,
    UnknownName,
    UnknownRegion,
    UnplacedRegion,
)
from ukumari.expr import At, Last, Ref, walk
from ukumari.guard import schedule
from ukumari.result import Err, Ok, Result
from ukumari.shape import Span


def _construction(model: Authored) -> list[ModelError]:
    errors: list[ModelError] = []

    def report(error: ModelError) -> None:
        if error not in errors:
            errors.append(error)

    regions: set[str] = set()
    for region in model.regions:
        if region in regions:
            report(DuplicateRegion(region))
        regions.add(region)

    axes: set[str] = set()
    placed: dict[str, str] = {}
    for axis in model.axes:
        if axis.name in axes:
            report(DuplicateAxis(axis.name))
        axes.add(axis.name)
        for region in axis.regions:
            if region not in regions:
                report(UnknownRegion(region, f"axis {axis.name!r}"))
            elif region in placed:
                report(RegionOnTwoAxes(region, (placed[region], axis.name)))
            else:
                placed[region] = axis.name
    for region in model.regions:
        if region not in placed:
            report(UnplacedRegion(region))

    kinds: dict[str, Kind] = {}
    for declaration in model.declarations:
        if declaration.name in kinds:
            report(DuplicateName(declaration.name))
        else:
            kinds[declaration.name] = declaration.kind
        shape = declaration.shape
        if isinstance(shape, Span) and shape.region not in regions:
            report(UnknownRegion(shape.region, repr(declaration.name)))

    defined: set[str] = set()
    for equation in model.equations:
        name = equation.name
        match kinds.get(name):
            case None:
                report(UnknownName(name, None))
            case Kind.INPUT:
                report(DefinedInput(name))
            case Kind.VECTOR if name in defined:
                report(Redefined(name))
            case Kind.VECTOR:
                defined.add(name)
        for node in walk(equation.expression):
            match node:
                case Ref(used) | Last(used) if used not in kinds:
                    report(UnknownName(used, name))
                case At():
                    raise AssertionError("an authored model holds no At")
                case _:
                    pass
    for declaration in model.declarations:
        if declaration.kind is Kind.VECTOR and declaration.name not in defined:
            report(Undefined(declaration.name))
    return errors


def check(model: Authored) -> Result[Circuit, tuple[ModelError, ...]]:
    """An L, or every error in the model at once."""
    errors = _construction(model)
    shapes: dict[str, Declaration] = {}
    for declaration in model.declarations:
        shapes.setdefault(declaration.name, declaration)
    vectors = [
        e
        for e in model.equations
        if e.name in shapes and shapes[e.name].kind is Kind.VECTOR
    ]
    guard_errors, layers = schedule(vectors)
    errors += guard_errors
    errors += align(
        model.axes,
        {name: d.shape for name, d in shapes.items()},
        tuple(vectors),
    )
    if errors:
        return Err(tuple(errors))
    return Ok(
        Circuit(
            axes=model.axes,
            declarations=model.declarations,
            equations=tuple(Equation(e.name, e.expression) for e in model.equations),
            schedule=layers,
        )
    )
