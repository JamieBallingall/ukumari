"""Random guarded models, shared by the tests that compare two computations of one thing."""

import itertools
import random
from fractions import Fraction

from ukumari.circuit import Equation
from ukumari.expr import Binary, Expr, First, Lag, Last, Literal, Neg, Op, Ref, walk
from ukumari.shape import Axis, Scalar, Shape, Span, scalar


def random_model(
    rng: random.Random, friendly: bool = False
) -> tuple[tuple[Axis, ...], dict[str, Shape], tuple[Equation, ...]]:
    """A random guarded model: up to three regions on up to two axes, trims up to two.

    A ``friendly`` model has one region, trims only at the front, and mostly seeded lags,
    so far more of them pass the gate with a recurrence in them.
    """
    regions = [f"r{i}" for i in range(1 if friendly else rng.randint(1, 3))]
    axis_names = [f"a{i}" for i in range(1 if friendly else rng.randint(1, 2))]
    placed: dict[str, list[str]] = {a: [] for a in axis_names}
    for r in regions:
        placed[rng.choice(axis_names)].append(r)
    axes = tuple(Axis(a, tuple(rs)) for a, rs in placed.items())

    def shape() -> Shape:
        if rng.random() < 0.2:
            return scalar
        if friendly:
            return Span(regions[0], rng.choice([0, 0, 1]), 0)
        return Span(rng.choice(regions), rng.randint(0, 2), rng.randint(0, 2))

    inputs = {f"in{i}": shape() for i in range(rng.randint(1, 3))}
    vectors = {f"v{i}": shape() for i in range(rng.randint(1, 4))}
    shapes = inputs | vectors
    names = list(shapes)
    scalar_inputs = [n for n in inputs if isinstance(inputs[n], Scalar)]
    # A vector is closed when neither it nor anything it reads refers forward. A reduction
    # of a closed vector can never sit on a cycle, so reductions may take inputs and closed
    # vectors: that exercises layers beyond the first.
    closed: set[str] = set()

    def reducible(defining: int) -> list[str]:
        return list(inputs) + [f"v{j}" for j in range(defining) if f"v{j}" in closed]

    reductions = itertools.count()

    def reduction(name: str) -> Expr:
        # Every third reduction is first() rather than last(). Choosing it by count, not by
        # a random draw, leaves the random stream, and so every model's shape, as it was.
        return First(name) if next(reductions) % 3 == 2 else Last(name)

    def seed(defining: int) -> Expr:
        pick = rng.random()
        if pick < 0.3:
            return Literal(Fraction(rng.randint(0, 3)))
        if pick < 0.6:
            return reduction(rng.choice(reducible(defining)))
        if scalar_inputs and pick < 0.85:
            return Ref(rng.choice(scalar_inputs))
        return Ref(rng.choice(list(inputs) + [f"v{j}" for j in range(defining)]))

    def expression(defining: int, depth: int, lagged: bool) -> Expr:
        # Forward references (to this vector or a later one) only under a lag, so every
        # cycle crosses one.
        if depth == 0 or rng.random() < 0.3:
            pick = rng.random()
            if pick < 0.1:
                return Literal(Fraction(rng.randint(0, 3)))
            if pick < 0.25:
                return reduction(rng.choice(reducible(defining)))
            allowed = list(inputs) + [f"v{i}" for i in range(defining)]
            if lagged:
                # Under a lag anything goes; a friendly model mostly reads vectors there,
                # which is what makes recurrences.
                allowed = list(vectors) if friendly and rng.random() < 0.7 else names
            return Ref(rng.choice(allowed))
        pick = rng.random()
        if pick < 0.15:
            return Neg(expression(defining, depth - 1, lagged))
        if pick < 0.5:
            return Binary(
                rng.choice(list(Op)),
                expression(defining, depth - 1, lagged),
                expression(defining, depth - 1, lagged),
            )
        body = expression(defining, depth - 1, True)
        seeded = rng.random() < (0.85 if friendly else 0.5)
        return Lag(body, seed(defining) if seeded else None)

    equations: list[Equation] = []
    for i in range(len(vectors)):
        body = expression(i, 3, False)
        read = {
            node.name for node in walk(body) if isinstance(node, Ref | Last | First)
        } & set(vectors)
        if all(name in closed for name in read):
            closed.add(f"v{i}")
        equations.append(Equation(f"v{i}", body))
    return axes, shapes, tuple(equations)


def three_statement_data(forecast: int = 5, actual: int = 1) -> dict[str, list[float]]:
    """The three-statement example's data at other lengths. Every figure is made up.

    The actual balance sheet balances in every actual year.
    """
    growth = [0.08, 0.07, 0.06, 0.05, 0.04]
    growth += [0.03] * max(0, forecast - len(growth))
    history = {
        "revenue_actual": [880, 950, 1000],
        "cash_actual": [100, 110, 120],
        "receivables_actual": [132, 140, 150],
        "ppe_actual": [580, 590, 600],
        "payables_actual": [80, 85, 90],
        "debt_actual": [340, 320, 300],
        "equity_actual": [392, 435, 480],
    }
    assert 1 <= actual <= 3
    first_forecast = 2026
    data: dict[str, list[float]] = {
        "year_actual": list(range(first_forecast - actual, first_forecast)),
        "year": list(range(first_forecast, first_forecast + forecast)),
        "growth": growth[:forecast],
        "scheduled_repayment": [50] * forecast,
        "cost_of_sales_pct": [0.60],
        "operating_expense_pct": [0.20],
        "depreciation_rate": [0.10],
        "interest_rate": [0.05],
        "tax_rate": [0.25],
        "receivables_pct": [0.15],
        "payables_pct": [0.15],
        "capex_pct": [0.08],
        "payout_ratio": [0.40],
    }
    for name, values in history.items():
        data[name] = list(values[-actual:])
    return data
