"""Milestone 1: the three-statement example meets each criterion, one test apiece."""

from fractions import Fraction
from pathlib import Path

import debt_schedule
import numpy as np
import pytest
import three_statement
from models import three_statement_data
from oracle import needs_the_app, oracle
from yupana import Formula, Text
from yupana.result import Err, Ok

from ukumari.agree import check_agreement, program_cells
from ukumari.bind import bind
from ukumari.check import check
from ukumari.circuit import Authored, Equation
from ukumari.emit import emit, load
from ukumari.errors import Undefined, UnguardedCycle
from ukumari.evaluate import cell_values
from ukumari.expr import Binary, Literal, Op, Ref, walk
from ukumari.pipeline import balanced, export
from ukumari.uku import load_uku, write_uku
from ukumari.unroll import unroll

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_1_is_text() -> None:
    """build() holds no data: its only literal is the 1 in ``1 + growth``."""
    circuit = three_statement.build().unwrap()
    literals = {
        node.value
        for equation in circuit.equations
        for node in walk(equation.expression)
        if isinstance(node, Literal)
    }
    assert literals == {Fraction(1)}


def test_2_is_checked() -> None:
    """A broken copy is refused with every error named, in one report."""
    circuit = three_statement.build().unwrap()
    equations = []
    for equation in circuit.equations:
        if equation.name == "debt":
            # A cycle with no lag in it: debt from debt at the same position.
            broken = Binary(Op.ADD, Ref("debt"), Ref("debt_repayment"))
            equations.append(Equation("debt", broken))
        elif equation.name != "check":  # declared, never defined
            equations.append(equation)
    authored = Authored(
        regions=tuple(r for axis in circuit.axes for r in axis.regions),
        axes=circuit.axes,
        declarations=circuit.declarations,
        equations=tuple(equations),
    )
    match check(authored):
        case Err(errors):
            assert UnguardedCycle(("debt",)) in errors
            assert Undefined("check") in errors
            report = "\n".join(str(e) for e in errors)
            assert "'check' is declared but never defined" in report
            assert "no lag crosses" in report
        case Ok():
            raise AssertionError("the broken copy was accepted")


def test_3_becomes_a_workbook() -> None:
    """The .yup reads back cleanly, with labels, indents, formats and widths, and yupana
    writes it as a workbook. That the app opens it is the test after this one."""
    result = export(
        three_statement.build().unwrap(),
        three_statement.data(),
        layout=three_statement.layout(),
    ).unwrap()
    cells = result.checked.cells
    formats = [c.format for c in cells]
    assert any(f.indent for f in formats)
    assert any(f.number_format is not None for f in formats)
    assert any(f.column_width == 34.0 for f in formats)
    assert any(c.content == Text("Revenue growth") for c in cells)
    assert sum(isinstance(c.content, Formula) for c in cells) > 100
    assert result.xlsx().unwrap()[:2] == b"PK"


@pytest.mark.app
@needs_the_app
def test_3_the_app_opens_the_workbook_and_computes_the_same() -> None:
    """The app opens yupana's workbook without complaint, and computes P's values."""
    result = export(
        three_statement.build().unwrap(),
        three_statement.data(),
        layout=three_statement.layout(),
    ).unwrap()
    target = Path(__file__).resolve().parents[1] / "target"
    target.mkdir(exist_ok=True)
    workbook = target / "three_statement.xlsx"
    workbook.write_bytes(result.xlsx().unwrap())
    finished = oracle(
        "compare",
        str(EXAMPLES / "three_statement.yup"),
        str(EXAMPLES / "three_statement.values.csv"),
        "--xlsx",
        str(workbook),
        "--tolerance",
        "1e-9",
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr


@pytest.mark.app
@needs_the_app
def test_4_agrees_with_the_app() -> None:
    """The oracle has the app compute the committed .yup, and every cell must agree."""
    finished = oracle(
        "compare",
        str(EXAMPLES / "three_statement.yup"),
        str(EXAMPLES / "three_statement.values.csv"),
        "--tolerance",
        "1e-9",
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr


def test_5_balances() -> None:
    program = load(emit(three_statement.build().unwrap()))
    out = program.run(three_statement.data())
    assert balanced(out["check"][0].tolist())
    assert balanced(out["check_actual"][0].tolist())


def test_6_has_no_fixed_horizon() -> None:
    circuit = three_statement.build().unwrap()
    for forecast, actual in [(10, 1), (5, 2)]:
        result = export(circuit, three_statement_data(forecast, actual)).unwrap()
        assert result.outputs["check"].shape == (1, forecast)
        assert balanced(result.outputs["check"][0].tolist())
        assert balanced(result.outputs["check_actual"][0].tolist())


def test_7_runs_in_a_loop() -> None:
    circuit = three_statement.build().unwrap()
    program = load(emit(circuit))
    data = three_statement.data()
    inputs = {name: np.asarray([values], dtype=float) for name, values in data.items()}
    rates = np.linspace(0.0, 0.10, 1000)
    inputs["growth"] = np.repeat(rates[:, None], 5, axis=1)
    out = program.run(inputs)
    assert out["cash"].shape == (1000, 5)
    for k in (0, 250, 500, 750, 999):
        single = dict(data)
        single["growth"] = [float(rates[k])] * 5
        bound = bind(circuit, single).unwrap()
        expected = cell_values(unroll(bound), bound.inputs)
        got = program_cells(bound, out, scenario=k)
        check_agreement(got, {cell: expected[cell] for cell in got})


def test_8_is_data() -> None:
    for example in (three_statement, debt_schedule):
        circuit = example.build().unwrap()
        assert load_uku(write_uku(circuit)) == Ok(circuit)
        for name, text in example.outputs().items():
            committed = (EXAMPLES / name).read_bytes().decode("utf-8")
            assert committed == text, f"{name} differs: run examples/regenerate.py"


def test_the_committed_model_file_builds_the_same_workbook() -> None:
    """The committed .uku, read back, gives the same .yup as the script does."""
    text = (EXAMPLES / "three_statement.uku").read_bytes().decode("utf-8")
    circuit = load_uku(text).unwrap()
    from_file = export(circuit, three_statement.data(), layout=three_statement.layout())
    committed = (EXAMPLES / "three_statement.yup").read_bytes().decode("utf-8")
    assert from_file.unwrap().yup == committed
    assert circuit == three_statement.build().unwrap()
