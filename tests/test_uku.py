"""``.uku`` round trips, its errors, and model inputs as CSV."""

import json
import random

import debt_schedule
import three_statement
from models import random_model
from yupana.result import Err, Ok

from ukumari import Model, lag, scalar
from ukumari.check import check
from ukumari.circuit import Authored, Declaration, Kind
from ukumari.errors import Undefined, UnguardedCycle
from ukumari.inputs import CsvError, read_inputs, write_inputs
from ukumari.uku import UkuError, load_uku, read_uku, write_uku


def test_writing_and_reading_back_gives_the_same_l() -> None:
    for example in (debt_schedule, three_statement):
        circuit = example.build().unwrap()
        text = write_uku(circuit)
        assert text.endswith("}\n") and "\r" not in text
        assert load_uku(text) == Ok(circuit)
        assert write_uku(load_uku(text).unwrap()) == text


def test_random_models_round_trip() -> None:
    rng = random.Random(11)
    done = 0
    while done < 200:
        axes, shapes, equations = random_model(rng)
        authored = Authored(
            regions=tuple(r for axis in axes for r in axis.regions),
            axes=axes,
            declarations=tuple(
                Declaration(
                    name, Kind.INPUT if name.startswith("in") else Kind.VECTOR, shape
                )
                for name, shape in shapes.items()
            ),
            equations=equations,
        )
        match check(authored):
            case Ok(circuit):
                assert load_uku(write_uku(circuit)) == Ok(circuit)
                done += 1
            case Err():
                pass


def test_one_line_per_equation_so_a_change_is_a_small_diff() -> None:
    text = write_uku(debt_schedule.build().unwrap())
    lines = text.splitlines()
    equations = [line for line in lines if '"expression"' in line]
    assert len(equations) == 3
    assert lines[1] == '  "format": "ukumari.model",'


def test_a_literal_is_an_exact_rational() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    x = m.input("x", t)
    y = m.vector("y", t)
    y.define(x * 0.1 + 1 / 3)
    text = write_uku(m.build().unwrap())
    assert '"value": "1/10"' in text
    # A float is read as what the author typed, through its repr: 1 / 3 is the float
    # 0.3333333333333333, which is read as that decimal exactly.
    assert '"value": "3333333333333333/10000000000000000"' in text


def test_structural_problems_are_all_reported_with_paths() -> None:
    document = {
        "format": "something.else",
        "version": 2,
        "axes": [{"name": "time", "regions": ["t", 7]}],
        "declarations": [
            {
                "name": "x",
                "kind": "input",
                "shape": {"region": "t", "front": -1, "back": 0},
            },
            {"name": "y", "kind": "table", "shape": "scalar"},
        ],
        "equations": [
            {
                "name": "y",
                "expression": {"op": "add", "left": {"op": "pow"}, "right": 1},
            },
            {"name": "z", "expression": {"op": "literal", "value": 0.5}, "extra": True},
        ],
    }
    match read_uku(json.dumps(document)):
        case Err(errors):
            paths = {e.path for e in errors}
            assert paths >= {
                "format",
                "version",
                "axes[0].regions[1]",
                "declarations[0].shape.front",
                "declarations[1].kind",
                "equations[0].expression.left.op",
                "equations[0].expression.right",
                "equations[1].extra",
            }
            assert (
                UkuError("equations[0].expression.left.op", 'unknown operation "pow"')
                in errors
            )
        case Ok():
            raise AssertionError("expected errors")


def test_not_json_is_one_error() -> None:
    match read_uku("{not json"):
        case Err((error,)):
            assert str(error).startswith("not JSON")
        case _:
            raise AssertionError("expected one error")


def test_a_file_passes_the_model_gate_like_a_script() -> None:
    document = {
        "format": "ukumari.model",
        "version": 1,
        "axes": [{"name": "time", "regions": ["t"]}],
        "declarations": [
            {
                "name": "a",
                "kind": "vector",
                "shape": {"region": "t", "front": 0, "back": 0},
            },
            {
                "name": "b",
                "kind": "vector",
                "shape": {"region": "t", "front": 0, "back": 0},
            },
            {"name": "c", "kind": "vector", "shape": "scalar"},
        ],
        "equations": [
            {"name": "a", "expression": {"op": "name", "name": "b"}},
            {"name": "b", "expression": {"op": "name", "name": "a"}},
        ],
    }
    match load_uku(json.dumps(document)):
        case Err(errors):
            assert set(errors) == {UnguardedCycle(("a", "b")), Undefined("c")}
        case Ok():
            raise AssertionError("expected model errors")


def test_hostile_names_round_trip() -> None:
    hostile = ['"}], "equations": []}', "new\nline", "tab\tand \\ backslash", "ünï"]
    m = Model()
    t = m.region(hostile[1])
    m.axis(hostile[2], t)
    k = m.input(hostile[0], scalar)
    v = m.vector(hostile[3], t)
    v.define(lag(v, seed=k) * 2)
    circuit = m.build().unwrap()
    assert load_uku(write_uku(circuit)) == Ok(circuit)


def test_inputs_csv_round_trips_and_reports_every_problem() -> None:
    data = {"growth": [0.08, 0.07, -0.0, 1e-300], "tax": [0.25]}
    assert read_inputs(write_inputs(data)) == Ok(
        {"growth": (0.08, 0.07, -0.0, 1e-300), "tax": (0.25,)}
    )
    # Line 3 repeats a position, line 4 leaves a gap at 1, line 5 has a leading zero,
    # line 6 a number outside JSON's grammar, and line 7 too few fields.
    text = "input,position,value\na,0,1\na,0,2\na,2,3\nb,01,4\nc,0,.5\nd,0\n"
    match read_inputs(text):
        case Err(errors):
            assert CsvError(3, "'a' position 0 repeats line 2") in errors
            assert CsvError(0, "'a' has no value at position 1") in errors
            assert any(e.line == 5 for e in errors)
            assert any(e.line == 6 for e in errors)
            assert CsvError(7, "needs 3 fields, not 2") in errors
        case Ok():
            raise AssertionError("expected errors")
    assert read_inputs("name,position,value\n") == Err(
        (CsvError(1, "the header must be input,position,value"),)
    )
