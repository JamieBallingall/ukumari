"""Binding, the unroll, the S evaluator and P: two computations that must agree."""

import math
import random
from collections.abc import Mapping, Sequence
from types import ModuleType

import debt_schedule
import numpy as np
import pytest
import three_statement
from models import random_model, three_statement_data
from yupana.result import Err, Ok

from ukumari import Model, lag, last, minimum, power, scalar
from ukumari.agree import check_agreement, program_cells, same
from ukumari.bind import (
    Bound,
    ConflictingExtent,
    EmptyRegion,
    MissingExtent,
    MissingInput,
    UnknownExtent,
    UnknownInput,
    WrongLength,
    bind,
)
from ukumari.check import check
from ukumari.circuit import Authored, Circuit, Declaration, Kind
from ukumari.emit import emit, load
from ukumari.evaluate import cell_values
from ukumari.shape import Span
from ukumari.unroll import Cell, Const, Element, Operation, Prim, unroll


def s_cells(
    circuit: Circuit,
    data: Mapping[str, Sequence[float]],
    extents: Mapping[str, int] | None = None,
) -> tuple[Bound, dict[Cell, float]]:
    bound = bind(circuit, data, extents).unwrap()
    return bound, cell_values(unroll(bound), bound.inputs)


def agree(
    circuit: Circuit,
    program: ModuleType,
    data: Mapping[str, Sequence[float]],
    extents: Mapping[str, int] | None = None,
) -> None:
    bound, expected = s_cells(circuit, data, extents)
    got = program_cells(bound, program.run(data, extents))
    check_agreement(got, {cell: expected[cell] for cell in got})


def test_the_first_forecast_year_matches_the_hand_worked_figures() -> None:
    circuit = three_statement.build().unwrap()
    _, values = s_cells(circuit, three_statement.data())
    by_hand = {
        "revenue": 1080,
        "cost_of_sales": 648,
        "gross_profit": 432,
        "operating_expenses": 216,
        "depreciation": 60,
        "operating_profit": 156,
        "interest": 15,
        "profit_before_tax": 141,
        "tax": 35.25,
        "net_income": 105.75,
    }
    for name, figure in by_hand.items():
        assert values[(name, 1)] == pytest.approx(figure, abs=1e-9), name


def test_one_emitted_debt_schedule_agrees_at_1_9_and_360_periods() -> None:
    circuit = debt_schedule.build().unwrap()
    program = load(emit(circuit))
    for periods in (1, 9, 360):
        data = {"principal": [1000.0], "scheduled": [7.25] * periods}
        agree(circuit, program, data)


def test_one_emitted_three_statement_program_agrees_at_1_9_and_360_years() -> None:
    circuit = three_statement.build().unwrap()
    program = load(emit(circuit))
    for forecast in (1, 9, 360):
        agree(circuit, program, three_statement_data(forecast))


def test_the_three_statement_model_balances_at_other_lengths() -> None:
    circuit = three_statement.build().unwrap()
    program = load(emit(circuit))
    for forecast, actual in [(5, 1), (10, 1), (5, 2), (10, 3)]:
        out = program.run(three_statement_data(forecast, actual))
        assert np.all(np.abs(out["check"]) <= 1e-9), (forecast, actual)
        assert np.all(np.abs(out["check_actual"]) <= 1e-9)
        assert out["check"].shape == (1, forecast)
        assert np.all(out["debt"] >= 0)


def test_a_sweep_runs_in_one_call_and_agrees_on_a_sample() -> None:
    circuit = three_statement.build().unwrap()
    program = load(emit(circuit))
    data = three_statement.data()
    rates = np.linspace(0.0, 0.10, 1000)
    sweep = {name: np.asarray([values], dtype=float) for name, values in data.items()}
    sweep["growth"] = np.repeat(rates[:, None], 5, axis=1)
    out = program.run(sweep)
    assert out["revenue"].shape == (1000, 5)
    assert out["check"].shape == (1000, 5)
    bound = bind(circuit, data).unwrap()
    for k in (0, 1, 499, 998, 999):
        single = dict(data)
        single["growth"] = [float(g) for g in sweep["growth"][k]]
        _, expected = s_cells(circuit, single)
        got = program_cells(bound, out, scenario=k)
        check_agreement(got, {c: expected[c] for c in got})


def test_requested_outputs_only() -> None:
    circuit = three_statement.build().unwrap()
    program = load(emit(circuit))
    out = program.run(three_statement.data(), outputs=["gross_profit"])
    assert list(out) == ["gross_profit"]
    assert out["gross_profit"][0, 0] == pytest.approx(432)
    with pytest.raises(ValueError, match="'nonsense' is not an output"):
        program.run(three_statement.data(), outputs=["nonsense"])


def test_the_program_declares_its_inputs_and_outputs() -> None:
    program = load(emit(debt_schedule.build().unwrap()))
    assert program.INPUTS == ("principal", "scheduled")
    assert program.OUTPUTS == ("opening", "payment", "closing")


def test_the_data_gate_reports_every_problem() -> None:
    circuit = three_statement.build().unwrap()
    data: dict[str, Sequence[float]] = dict(three_statement.data())
    data["growth"] = [0.1] * 6  # the other forecast inputs have 5
    data["tax_rate"] = [0.2, 0.3]
    del data["payout_ratio"]
    data["surprise"] = [1.0]
    match bind(circuit, data, {"elsewhere": 3}):
        case Err(errors):
            assert set(errors) == {
                ConflictingExtent(
                    "forecast",
                    (("year", 5), ("growth", 6), ("scheduled_repayment", 5)),
                ),
                WrongLength("tax_rate", 1, 2),
                MissingInput("payout_ratio"),
                UnknownInput("surprise"),
                UnknownExtent("elsewhere"),
            }
        case Ok():
            raise AssertionError("expected data errors")
    program = load(emit(circuit))
    with pytest.raises(ValueError) as caught:
        program.run(data, {"elsewhere": 3})
    message = str(caught.value)
    for fragment in ("'surprise'", "'payout_ratio'", "'tax_rate'", "'forecast'"):
        assert fragment in message


def test_extents_given_explicitly_and_empty_spans() -> None:
    m = Model()
    history, forecast = m.region("history"), m.region("forecast")
    m.axis("year", history, forecast)
    x = m.input("x", history)
    y = m.vector("y", forecast[1:])
    y.define(lag(y, seed=last(x)) + 1)
    circuit = m.build().unwrap()
    assert bind(circuit, {"x": [1.0]}) == Err((MissingExtent("forecast"),))
    assert bind(circuit, {"x": [1.0]}, {"forecast": 1}) == Err(
        (EmptyRegion("y", "forecast"),)
    )
    bound = bind(circuit, {"x": [1.0]}, {"forecast": 3}).unwrap()
    interval = bound.intervals["y"]
    assert interval is not None
    assert (interval.start, interval.stop) == (2, 4)
    program = load(emit(circuit))
    out = program.run({"x": [5.0]}, {"forecast": 3})
    assert out["y"].tolist() == [[6.0, 7.0]]


def test_a_seeded_lag_whose_body_is_asked_for_nothing() -> None:
    """Under two seeded lags, a one-position target asks the inner body for fewer than no
    positions: P must take no columns, not a slice counted from the right."""
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    k = m.input("k", scalar)
    x = m.input("x", t)
    twice = m.vector("twice", t[:-2])
    twice.define(lag(lag(x, seed=k), seed=k))
    circuit = m.build().unwrap()
    program = load(emit(circuit))
    expected = {3: [7.0], 4: [7.0, 7.0], 6: [7.0, 7.0, 0.0, 1.0]}
    for n, values in expected.items():
        data = {"k": [7.0], "x": [float(i) for i in range(n)]}
        assert program.run(data)["twice"].tolist() == [values]
        agree(circuit, program, data)


def test_the_unroll_shares_nodes_but_never_literals() -> None:
    circuit = debt_schedule.build().unwrap()
    bound = bind(circuit, {"principal": [100.0], "scheduled": [30.0] * 3}).unwrap()
    s = unroll(bound)
    # opening[1] is closing[0]: the lag edge adds no node.
    assert s.cells[("opening", 1)] == s.cells[("closing", 0)]
    assert s.origins[s.cells[("opening", 1)]] == ("closing", 0)
    # opening[0] is the seed, which is the principal input's own cell.
    assert s.cells[("opening", 0)] == s.cells[("principal", None)]
    for number, node in enumerate(s.nodes):
        if isinstance(node, Operation):
            assert all(operand < number for operand in node.operands)

    m = Model()
    t = m.region("t")
    m.axis("time", t)
    a = m.input("a", t)
    b, c = m.vectors(t, "b", "c")
    b.define(a * 2)
    c.define(a * 2 + 2)
    s = unroll(bind(m.build().unwrap(), {"a": [1.0]}).unwrap())
    assert sum(isinstance(n, Const) for n in s.nodes) == 3  # every literal its own
    # So `a * 2` in `c` is not `b`: a subexpression holding a literal is never shared.
    root = s.nodes[s.cells[("c", 0)]]
    assert isinstance(root, Operation) and root.prim is Prim.ADD
    assert root.operands[0] != s.cells[("b", 0)]
    assert isinstance(s.nodes[0], Element)

    m = Model()
    t = m.region("t")
    m.axis("time", t)
    a, k = m.input("a", t), m.input("k", scalar)
    b, c = m.vectors(t, "b", "c")
    b.define(a * k)
    c.define(a * k + k)
    s = unroll(bind(m.build().unwrap(), {"a": [1.0], "k": [2.0]}).unwrap())
    # Without a literal, the shared subexpression is one node: c reads b's cell.
    assert s.nodes[s.cells[("c", 0)]] == Operation(
        Prim.ADD, (s.cells[("b", 0)], s.cells[("k", None)])
    )


def test_errors_and_signed_zeros_agree() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    a, b = m.input("a", t), m.input("b", t)
    q, lo, hi, n = m.vectors(t, "q", "lo", "hi", "n")
    q.define(a / b)
    lo.define(minimum(a, b))
    hi.define(-minimum(b, a))
    n.define(-(a * b) - a * b)
    circuit = m.build().unwrap()
    values = [0.0, -0.0, 1.0, -1.0, math.nan, math.inf, -math.inf, 1e308, 5e-324]
    pairs = [(x, y) for x in values for y in values]
    data = {"a": [x for x, _ in pairs], "b": [y for _, y in pairs]}
    agree(circuit, load(emit(circuit)), data)
    _, cells = s_cells(circuit, data)
    assert math.isnan(cells[("q", 1)])  # 0 / -0
    assert same(cells[("lo", 1)], -0.0)  # min(0, -0) is the second argument
    assert math.isnan(cells[("n", values.index(1e308) * len(values) + 7)])


def test_powers_and_their_errors_agree() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    a, b = m.input("a", t), m.input("b", t)
    m.vector("p", t).define(power(a, b))
    circuit = m.build().unwrap()
    values = [
        0.0,
        -0.0,
        1.0,
        -1.0,
        2.0,
        -8.0,
        0.5,
        1 / 3,
        -2.5,
        1e308,
        5e-324,
        math.nan,
    ]
    pairs = [(x, y) for x in values for y in values]
    data = {"a": [x for x, _ in pairs], "b": [y for _, y in pairs]}
    agree(circuit, load(emit(circuit)), data)
    _, cells = s_cells(circuit, data)

    def at(x: float, y: float) -> float:
        return cells[("p", values.index(x) * len(values) + values.index(y))]

    assert at(2.0, 0.5) == math.sqrt(2.0)
    assert at(-8.0, 2.0) == 64.0
    for x, y in [(0.0, 0.0), (0.0, -1.0), (-8.0, 1 / 3), (1.0, math.nan), (1e308, 2.0)]:
        assert math.isnan(at(x, y)), (x, y)
    # The app refuses a negative base to a power of 2**32 - 1 or more, though C does not.
    near = {"a": [-1.0, -1.0, -1.0], "b": [2.0**32 - 2, 2.0**32 - 1, -(2.0**32 - 1)]}
    agree(circuit, load(emit(circuit)), near)
    _, cells = s_cells(circuit, near)
    assert cells[("p", 0)] == 1.0
    assert math.isnan(cells[("p", 1)]) and math.isnan(cells[("p", 2)])


def random_data(rng: random.Random, n: int) -> list[float]:
    pool = [0.0, -0.0, 1.0, -1.0, 2.5, 1e308, -1e308, 1e-310, math.nan, math.inf]
    return [
        rng.choice(pool) if rng.random() < 0.3 else rng.uniform(-100, 100)
        for _ in range(n)
    ]


@pytest.mark.parametrize("friendly", [False, True])
def test_p_and_the_s_evaluator_agree_on_random_models(friendly: bool) -> None:
    rng = random.Random(7)
    compared = recurrent = layered = 0
    while compared < 300:
        axes, shapes, equations = random_model(rng, friendly)
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
            case Err():
                continue
            case Ok(circuit):
                pass
        lowest = {r: 1 for axis in axes for r in axis.regions}
        for shape in shapes.values():
            if isinstance(shape, Span):
                need = shape.front + shape.back + 1
                lowest[shape.region] = max(lowest[shape.region], need)
        extents = {r: low + rng.randint(0, 4) for r, low in lowest.items()}
        data: dict[str, list[float]] = {}
        carried: set[str] = set()
        for d in circuit.inputs():
            match d.shape:
                case Span(region, front, back):
                    carried.add(region)
                    data[d.name] = random_data(rng, extents[region] - front - back)
                case _:
                    data[d.name] = random_data(rng, 1)
        explicit = {r: e for r, e in extents.items() if r not in carried}
        agree(circuit, load(emit(circuit)), data, explicit)
        compared += 1
        layered += len(circuit.schedule) > 1
        recurrent += any(
            c.recurrent for layer in circuit.schedule for c in layer.components
        )
    if friendly:
        # The comparison means something only if recurrences and layers occur often.
        assert recurrent >= 80 and layered >= 20, (recurrent, layered)


def test_hostile_names_never_become_code() -> None:
    hostile = [
        "x'); __import__('os').system('echo pwned') #",
        '"""\nimport os\n"""',
        "line\nbreak",
        "back\\slash",
        "__import__('sys').exit(1)",
    ]
    m = Model()
    t = m.region(hostile[2])
    m.axis(hostile[3], t)
    k = m.input(hostile[0], scalar)
    values = m.input(hostile[1], t)
    out = m.vector(hostile[4], t)
    out.define(lag(out, seed=k) + values)
    # Emitted comments name vectors by repr, which escapes every line break Python knows.
    breaks = "carriage\rreturn\u2028separator\x85next"
    m.vector(breaks, t).define(out * 2)
    circuit = m.build().unwrap()
    source = emit(circuit)
    assert repr(breaks) in source and breaks not in source
    program = load(source)
    assert program.INPUTS == (hostile[0], hostile[1])
    data = {hostile[0]: [1.0], hostile[1]: [1.0, 2.0]}
    assert program.run(data)[hostile[4]].tolist() == [[2.0, 4.0]]
    agree(circuit, program, data)
