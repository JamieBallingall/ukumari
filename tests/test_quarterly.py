"""The quarterly example: it balances, keeps its seasons, and runs at any length."""

from pathlib import Path

import pytest
import quarterly
from oracle import needs_the_app, oracle
from yupana.result import Ok

from ukumari.emit import emit, load
from ukumari.pipeline import balanced, export
from ukumari.uku import load_uku, write_uku

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_it_balances_in_every_quarter() -> None:
    out = load(emit(quarterly.build().unwrap())).run(quarterly.data())
    assert balanced(out["balance_check"][0].tolist())
    assert balanced(out["balance_check_actual"][0].tolist())


def test_revenue_grows_on_the_same_quarter_a_year_earlier() -> None:
    data = quarterly.data()
    out = load(emit(quarterly.build().unwrap())).run(data)
    # The compound annual growth of twelve-month revenue, worked out here independently.
    reported = data["revenue_actual"]
    twelve_months = [sum(reported[t - 3 : t + 1]) for t in range(3, len(reported))]
    years = (len(twelve_months) - 1) / 4
    cagr = (twelve_months[-1] / twelve_months[0]) ** (1 / years) - 1
    assert out["cagr"][0, 0] == pytest.approx(cagr, rel=1e-12)
    revenue = out["revenue"][0].tolist()
    growth = out["revenue_growth"][0].tolist()
    year_earlier = reported[-4:] + revenue[:-4]
    for now, then, rate in zip(revenue, year_earlier, growth, strict=True):
        assert now == pytest.approx(then * (1 + rate), rel=1e-12)
    # Gardens still peak in the second quarter of every forecast year.
    for year in range(len(revenue) // 4):
        quarters = revenue[4 * year : 4 * year + 4]
        assert max(quarters) == quarters[1]


def test_the_surprise_follows_the_seasonal_autoregression() -> None:
    data = quarterly.data()
    out = load(emit(quarterly.build().unwrap())).run(data)
    reported = data["revenue_actual"]
    cagr = out["cagr"][0, 0]
    # Growth, less the compound growth and the economy measured from its average over
    # the quarters with a growth rate, is the surprise: worked out here independently.
    gdp, price = data["gdp_growth_actual"][4:], data["price_change_actual"][4:]
    gdp_average, price_average = sum(gdp) / len(gdp), sum(price) / len(price)
    gdp_beta, price_beta = data["gdp_beta"][0], data["price_beta"][0]
    surprise = [
        reported[t] / reported[t - 4]
        - 1
        - cagr
        - gdp_beta * (g - gdp_average)
        - price_beta * (p - price_average)
        for t, g, p in zip(range(4, len(reported)), gdp, price, strict=True)
    ]
    assert out["surprise_a"][0].tolist() == pytest.approx(surprise, abs=1e-15)
    # In the forecast, each surprise carries part of the last quarter's and part of the
    # same quarter's a year earlier: SARIMAX(1,0,0)(1,0,0) with a season of four.
    ar, seasonal_ar = data["ar"][0], data["seasonal_ar"][0]
    for _ in range(len(out["surprise"][0])):
        surprise.append(
            ar * surprise[-1]
            + seasonal_ar * surprise[-4]
            - ar * seasonal_ar * surprise[-5]
        )
    assert out["surprise"][0].tolist() == pytest.approx(surprise[16:], abs=1e-15)
    growth = [
        cagr + gdp_beta * (g - gdp_average) + price_beta * (p - price_average) + u
        for g, p, u in zip(
            data["gdp_growth"], data["price_change"], surprise[16:], strict=True
        )
    ]
    assert out["revenue_growth"][0].tolist() == pytest.approx(growth, abs=1e-15)


def test_the_waterfall_keeps_its_limits() -> None:
    data = quarterly.data()
    out = load(emit(quarterly.build().unwrap())).run(data)
    limit, floor = data["revolver_limit"][0], data["minimum_cash"][0]
    revolver = out["revolver"][0]
    assert all(0.0 <= r <= limit for r in revolver)
    assert all(0.0 <= d <= data["dividend"][0] for d in out["dividends"][0])
    assert all(b >= 0.0 for b in out["buybacks"][0])
    # Cash is at least the minimum, since the revolver never runs out here.
    assert all(c >= floor - 1e-9 for c in out["cash"][0])
    # The revolver peaks in the second quarter of every year, as inventory builds.
    for year in range(len(revolver) // 4):
        quarters = revolver[4 * year : 4 * year + 4].tolist()
        assert max(quarters) == quarters[1]


def test_each_bond_is_repaid_whole_at_maturity() -> None:
    data = quarterly.data()
    out = load(emit(quarterly.build().unwrap())).run(data)
    for name in ("bond_a", "bond_b"):
        face = data[f"{name}_actual"][-1]
        due = int(data[f"{name}_quarters"][0])
        assert out[name][0].tolist() == [face] * (due - 1) + [0.0] * (20 - due + 1)
        repaid = out[f"{name}_repaid"][0].tolist()
        assert repaid == [0.0] * (due - 1) + [face] + [0.0] * (20 - due)


def test_the_floating_debt_follows_the_base_rate() -> None:
    data = quarterly.data()
    program = load(emit(quarterly.build().unwrap()))
    base = program.run(data)
    higher = program.run(data | {"base_rate": [r + 0.01 for r in data["base_rate"]]})
    # A point more on the base rate is a quarter of a point more a quarter on the term
    # loan's opening balance, from the first quarter, before any other change feeds back.
    opening = base["opening_term_loan"][0, 0]
    extra = higher["term_loan_interest"][0, 0] - base["term_loan_interest"][0, 0]
    assert extra == pytest.approx(opening * 0.01 / 4, rel=1e-12)
    assert higher["interest"][0].sum() > base["interest"][0].sum()
    assert higher["net_income"][0].sum() < base["net_income"][0].sum()


def test_it_has_no_fixed_horizon() -> None:
    circuit = quarterly.build().unwrap()
    for history, forecast in [(9, 1), (12, 12), (20, 60)]:
        result = export(
            circuit, quarterly.data(history, forecast), layout=quarterly.workbook()
        ).unwrap()
        assert result.outputs["revenue"].shape == (1, forecast)
        assert balanced(result.outputs["balance_check"][0].tolist())
        assert balanced(result.outputs["balance_check_actual"][0].tolist())


def test_the_committed_files_are_what_the_code_writes() -> None:
    circuit = quarterly.build().unwrap()
    assert load_uku(write_uku(circuit)) == Ok(circuit)
    for name, text in quarterly.outputs().items():
        committed = (EXAMPLES / name).read_bytes().decode("utf-8")
        assert committed == text, f"{name} differs: run examples/regenerate.py"


@pytest.mark.app
@needs_the_app
def test_the_app_computes_the_committed_file_the_same() -> None:
    finished = oracle(
        "compare",
        str(EXAMPLES / "quarterly.yup"),
        str(EXAMPLES / "quarterly.values.csv"),
        "--tolerance",
        "1e-9",
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr


@pytest.mark.app
@needs_the_app
def test_the_app_opens_the_workbook_and_computes_the_same() -> None:
    result = export(
        quarterly.build().unwrap(), quarterly.data(), layout=quarterly.workbook()
    ).unwrap()
    target = Path(__file__).resolve().parents[1] / "target"
    target.mkdir(exist_ok=True)
    workbook = target / "quarterly.xlsx"
    workbook.write_bytes(result.xlsx().unwrap())
    finished = oracle(
        "compare",
        str(EXAMPLES / "quarterly.yup"),
        str(EXAMPLES / "quarterly.values.csv"),
        "--xlsx",
        str(workbook),
        "--tolerance",
        "1e-9",
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr
