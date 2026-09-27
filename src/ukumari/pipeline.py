"""The pipeline in one call: build, bind, unroll, lay out, run P, check, and write.

Every expected failure (a model error, a data error, an ``.sls`` file the reader refuses)
flows into one ``Result``. A disagreement between P and the S evaluator is a bug in
ukumari, so it raises ``AssertionError``; so does a layout written wrongly by hand, which
raises ``ValueError``.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import ModuleType

import numpy as np

from ukumari.agree import check_agreement, program_cells
from ukumari.bind import Bound, DataError, bind
from ukumari.circuit import Circuit, Kind
from ukumari.emit import emit, load
from ukumari.errors import ModelError
from ukumari.evaluate import cell_values
from ukumari.layout import Grid, Layout, grid
from ukumari.model import Model
from ukumari.result import Err, Ok, Result
from ukumari.sls import write_sls
from ukumari.stliss_stand_in import SlsError, read_sls
from ukumari.stliss_stand_in_xlsx import write_xlsx
from ukumari.unroll import Cell, Straight, unroll

type PipelineError = ModelError | DataError | SlsError


@dataclass(frozen=True, slots=True)
class Export:
    """Everything one run of a model produces."""

    circuit: Circuit
    bound: Bound
    straight: Straight
    grid: Grid
    program: str
    outputs: Mapping[str, np.ndarray]
    values: Mapping[Cell, float]
    sls: str
    values_csv: str

    def xlsx(self) -> bytes:
        """The workbook of live formulas.

        Written through the stand-in for ``stliss``'s xlsx writer, until ``stliss`` exists.
        """
        return write_xlsx(read_sls(self.sls).unwrap())


def export(
    model: Model | Circuit,
    inputs: Mapping[str, Sequence[float]],
    extents: Mapping[str, int] | None = None,
    layout: Layout | None = None,
    program: ModuleType | None = None,
) -> Result[Export, tuple[PipelineError, ...]]:
    """Run a model over one scenario of data, and write it as ``.sls`` and a values CSV.

    ``program`` replaces the emitted P, for tests that must see the check refuse.
    """
    if isinstance(model, Model):
        match model.build():
            case Err(model_errors):
                return Err(model_errors)
            case Ok(built):
                circuit = built
    else:
        circuit = model
    match bind(circuit, inputs, extents):
        case Err(data_errors):
            return Err(data_errors)
        case Ok(bound):
            pass
    straight = unroll(bound)
    placed = grid(layout or Layout(), circuit, bound.intervals)
    source = emit(circuit)
    runnable = program or load(source)
    outputs = runnable.run({k: list(v) for k, v in inputs.items()}, extents)

    computed = program_cells(bound, outputs)
    evaluated = cell_values(straight, bound.inputs)
    check_agreement(computed, {cell: evaluated[cell] for cell in computed})

    values: dict[Cell, float] = dict(computed)
    for d in circuit.declarations:
        if d.kind is Kind.INPUT:
            interval = bound.intervals[d.name]
            data = bound.inputs[d.name]
            if interval is None:
                values[(d.name, None)] = data[0]
            else:
                for index, t in enumerate(range(interval.start, interval.stop)):
                    values[(d.name, t)] = data[index]
    written = write_sls(straight, bound, placed, values)
    match read_sls(written.sls):
        case Err(sls_errors):
            return Err(sls_errors)
        case Ok():
            pass
    return Ok(
        Export(
            circuit=circuit,
            bound=bound,
            straight=straight,
            grid=placed,
            program=source,
            outputs=outputs,
            values=values,
            sls=written.sls,
            values_csv=written.values,
        )
    )


def balanced(values: Sequence[float], tolerance: float = 1e-9) -> bool:
    """Whether every value is within ``tolerance`` of zero, and none is an error."""
    return all(not math.isnan(v) and abs(v) <= tolerance for v in values)
