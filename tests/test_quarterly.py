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
    year_earlier = reported[-4:] + revenue[:-4]
    for now, then in zip(revenue, year_earlier, strict=True):
        assert now == pytest.approx(then * (1 + cagr), rel=1e-12)
    # Gardens still peak in the second quarter of every forecast year.
    for year in range(len(revenue) // 4):
        quarters = revenue[4 * year : 4 * year + 4]
        assert max(quarters) == quarters[1]


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
    # The revolver is drawn in the first half of every year and repaid in the second.
    assert revolver.max() > 20 and revolver[2::4].max() == 0.0


def test_it_has_no_fixed_horizon() -> None:
    circuit = quarterly.build().unwrap()
    for history, forecast in [(5, 1), (8, 12), (20, 60)]:
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
