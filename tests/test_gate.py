"""The model gate: construction, guardedness and alignment, reported together."""

from fractions import Fraction

import pytest
from yupana.result import Err, Ok

from ukumari import Model, first, lag, last, minimum, scalar
from ukumari.check import check
from ukumari.circuit import Authored, Component, Declaration, Equation, Kind, Layer
from ukumari.errors import (
    CircularReduction,
    DefinedInput,
    DuplicateAxis,
    DuplicateName,
    DuplicateRegion,
    LagBeforeStart,
    LagOffAxis,
    Misaligned,
    ModelError,
    Redefined,
    ReductionOfAScalar,
    RegionOnTwoAxes,
    SeedNotScalar,
    Undefined,
    UnguardedCycle,
    UnknownName,
    UnknownRegion,
    UnplacedRegion,
)
from ukumari.expr import Lag, Literal, Ref
from ukumari.shape import Axis, Span


def errors_of(m: Model) -> tuple[ModelError, ...]:
    match m.build():
        case Ok(circuit):
            raise AssertionError(f"expected errors, got {circuit}")
        case Err(errors):
            return errors


def test_the_debt_schedule_is_one_recurrence_in_dependency_order() -> None:
    m = Model()
    period = m.region("period")
    m.axis("month", period)
    scheduled = m.input("scheduled", period)
    # Defined out of order: the schedule still puts each position's inputs first.
    closing, payment, opening = m.vectors(period, "closing", "payment", "opening")
    closing.define(opening - payment)
    payment.define(minimum(scheduled, opening))
    opening.define(lag(closing, seed=100))
    circuit = m.build().unwrap()
    assert circuit.schedule == (
        Layer((Component(("opening", "payment", "closing"), recurrent=True),)),
    )


def test_a_broken_model_reports_every_error_at_once() -> None:
    """Criterion 2: a cycle with no lag, and a vector declared but never defined."""
    m = Model()
    year = m.region("year")
    m.axis("time", year)
    growth = m.input("growth", year)
    revenue, cost, profit, _forgotten = m.vectors(
        year, "revenue", "cost", "profit", "forgotten"
    )
    revenue.define(profit * (1 + growth))  # profit needs revenue: no lag anywhere
    cost.define(revenue * 0.6)
    profit.define(revenue - cost)
    errors = errors_of(m)
    assert Undefined("forgotten") in errors
    assert any(isinstance(e, UnguardedCycle) for e in errors)
    assert len(errors) == 2
    messages = "\n".join(str(e) for e in errors)
    assert "'forgotten' is declared but never defined" in messages
    assert "no lag crosses" in messages


def test_an_unguarded_cycle_names_a_path_through_it() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    a, b = m.vectors(t, "a", "b")
    a.define(b + 1)
    b.define(a * 2)
    (error,) = errors_of(m)
    assert error == UnguardedCycle(("a", "b"))
    assert str(error) == "a cycle of references that no lag crosses: 'a' -> 'b' -> 'a'"


def test_a_self_reference_needs_a_lag() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    (x,) = m.vectors(t, "x")
    x.define(x + 1)
    assert errors_of(m) == (UnguardedCycle(("x",)),)


def test_construction_errors() -> None:
    m = Model()
    t = m.region("t")
    m.region("t")
    m.region("loose")
    m.axis("time", t)
    m.axis("time", t)
    x = m.vector("x", t)
    m.vector("x", t)
    inp = m.input("inp", t)
    x.define(1)
    x.define(2)
    inp.define(3)
    errors = errors_of(m)
    assert DuplicateRegion("t") in errors
    assert UnplacedRegion("loose") in errors
    assert DuplicateAxis("time") in errors
    assert RegionOnTwoAxes("t", ("time", "time")) in errors
    assert DuplicateName("x") in errors
    assert Redefined("x") in errors
    assert DefinedInput("inp") in errors


def test_unknown_names_and_regions_from_an_authored_model() -> None:
    authored = Authored(
        regions=("t",),
        axes=(Axis("time", ("t", "nowhere")),),
        declarations=(
            Declaration("x", Kind.VECTOR, Span("t")),
            Declaration("y", Kind.VECTOR, Span("elsewhere")),
        ),
        equations=(
            Equation("x", Ref("ghost") + 1),
            Equation("y", Literal(Fraction(1))),
            Equation("z", Literal(Fraction(2))),
        ),
    )
    match check(authored):
        case Err(errors):
            assert UnknownRegion("nowhere", "axis 'time'") in errors
            assert UnknownRegion("elsewhere", "'y'") in errors
            assert UnknownName("ghost", "x") in errors
            assert UnknownName("z", None) in errors
        case Ok():
            raise AssertionError("expected errors")


def test_defining_an_expression_is_a_bug_in_the_script() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    x = m.vector("x", t)
    with pytest.raises(TypeError, match="only a declared vector can be defined"):
        (x + 1).define(2)


def test_misaligned_leaves_say_which_end() -> None:
    m = Model()
    history, forecast = m.region("history"), m.region("forecast")
    m.axis("year", history, forecast)
    sales = m.input("sales", forecast)
    early = m.vector("early", history)
    late = m.vector("late", forecast)
    early.define(sales * 2)  # sales does not reach back into history
    late.define(lag(sales))  # forecast[0] would read the position before forecast
    errors = errors_of(m)
    assert Misaligned("early", "sales", "before") in errors
    assert Misaligned("late", "sales", "before") in errors
    assert len(errors) == 2


def test_a_trimmed_span_makes_room_for_an_unseeded_lag() -> None:
    m = Model()
    history = m.region("history")
    m.axis("year", history)
    revenue = m.input("revenue", history)
    growth = m.vector("growth", history[1:])
    growth.define(revenue / lag(revenue) - 1)
    assert m.build().is_ok()


def test_an_unseeded_lag_at_the_start_of_the_axis() -> None:
    m = Model()
    history = m.region("history")
    m.axis("year", history)
    revenue = m.input("revenue", history)
    growth = m.vector("growth", history)
    growth.define(revenue / lag(revenue) - 1)
    errors = errors_of(m)
    assert LagBeforeStart("growth", "year") in errors
    assert Misaligned("growth", "revenue", "before") in errors


def test_reading_past_the_end() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    short = m.input("short", t[:-1])
    full = m.vector("full", t)
    full.define(short + 1)
    assert errors_of(m) == (Misaligned("full", "short", "after"),)


def test_a_vector_on_another_axis() -> None:
    m = Model()
    a, b = m.region("a"), m.region("b")
    m.axis("one", a)
    m.axis("two", b)
    x = m.input("x", a)
    y = m.vector("y", b)
    y.define(x)
    assert errors_of(m) == (Misaligned("y", "x", "axis"),)


def test_scalar_equations_read_vectors_only_through_reductions() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    x = m.input("x", t)
    rate = m.input("rate", scalar)
    good, bad, lagged, reduced = m.vectors(scalar, "good", "bad", "lagged", "reduced")
    good.define(last(x) * rate)
    bad.define(x * rate)
    lagged.define(lag(rate, seed=0))
    reduced.define(last(rate))
    errors = errors_of(m)
    assert set(errors) == {
        Misaligned("bad", "x", "scalar"),
        LagOffAxis("lagged"),
        ReductionOfAScalar("reduced", "rate"),
    }


def test_a_seed_must_be_a_single_value() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    x = m.input("x", t)
    y = m.vector("y", t)
    y.define(lag(y, seed=x))
    assert errors_of(m) == (SeedNotScalar("y", "x"),)


def test_a_reduction_on_a_cycle() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    x = m.vector("x", t)
    x.define(lag(x, seed=0) + last(x))
    assert errors_of(m) == (CircularReduction("x", "x"),)


def test_first_is_a_reduction_like_last() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    x = m.input("x", t)
    rate = m.input("rate", scalar)
    y = m.vector("y", t)
    y.define(lag(y, seed=first(x)) + first(y))
    ratio, of_scalar = m.vectors(scalar, "ratio", "of_scalar")
    ratio.define(last(x) / first(x))
    of_scalar.define(first(rate))
    assert set(errors_of(m)) == {
        CircularReduction("y", "y"),
        ReductionOfAScalar("of_scalar", "rate"),
    }
    with pytest.raises(TypeError, match="first"):
        first(x * 2)  # ty: ignore[invalid-argument-type]


def test_a_reduction_starts_a_new_layer() -> None:
    m = Model()
    a, b = m.region("a"), m.region("b")
    m.axis("time", a, b)
    x = m.input("x", a)
    first = m.vector("first", a)
    total = m.vector("total", scalar)
    second = m.vector("second", b)
    second.define(total * 2)
    total.define(last(first))
    first.define(x + 1)
    circuit = m.build().unwrap()
    assert [[c.members for c in layer.components] for layer in circuit.schedule] == [
        [("first",)],
        [("total",), ("second",)],
    ]


def test_a_seeded_lag_over_one_element_asks_nothing_of_its_body() -> None:
    # `x` exists only on the first position of `b`; a seeded lag on a one-element span
    # never reads it, so this is aligned. On two elements it would read x at b[0] only.
    m = Model()
    b = m.region("b")
    m.axis("time", b)
    x = m.input("x", b[:-1])
    y = m.vector("y", b)
    y.define(lag(x, seed=0))
    assert m.build().is_ok()
    m2 = Model()
    b2 = m2.region("b")
    m2.axis("time", b2)
    x2 = m2.input("x", b2[:-1])
    y2 = m2.vector("y", b2)
    y2.define(lag(lag(x2, seed=0), seed=0))
    assert m2.build().is_ok()
    m3 = Model()
    b3 = m3.region("b")
    m3.axis("time", b3)
    x3 = m3.input("x", b3[:-2])
    y3 = m3.vector("y", b3)
    y3.define(lag(x3, seed=0))
    assert errors_of(m3) == (Misaligned("y", "x", "after"),)


def test_guardedness_and_alignment_are_reported_together() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    x = m.input("x", t[1:])
    a, b = m.vectors(t, "a", "b")
    a.define(b + x)
    b.define(a)
    errors = errors_of(m)
    assert UnguardedCycle(("a", "b")) in errors
    assert Misaligned("a", "x", "before") in errors


def test_lag_of_a_lag_is_two_back() -> None:
    authored_seed = Lag(Lag(Ref("x"), Literal(Fraction(0))), None)
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    m.input("x", t)
    y = m.vector("y", t[1:])
    y.define(authored_seed)
    assert m.build().is_ok()
