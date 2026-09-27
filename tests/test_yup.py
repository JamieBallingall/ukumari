"""β₁: the ``.yup`` writer, its formulas, and the pipeline that checks P against S."""

import math
from types import ModuleType

import debt_schedule
import numpy as np
import pytest
import three_statement
from yupana import PREAMBLE, YupError
from yupana.result import Err

from ukumari import Layout, Model, first, lag, last, maximum, minimum, scalar
from ukumari.emit import emit, load
from ukumari.layout import Address
from ukumari.pipeline import export
from ukumari.shape import Span


def cells_of(yup: str) -> dict[tuple[int, int], tuple[str, str]]:
    """(row, col) → (cell, format), from ``.yup`` text."""
    found = {}
    for line in yup.splitlines()[2:]:
        _, row, col, cell, fmt = line.split("\t")
        found[(int(row), int(col))] = (cell, fmt)
    return found


def formula(m: Model, data: dict[str, list[float]], name: str) -> str:
    result = export(m, data).unwrap()
    at = result.grid.address(name, 0)
    return cells_of(result.yup)[(at.row, at.column)][0]


def small() -> tuple[Model, Span]:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    return m, t


def test_parentheses_only_where_needed() -> None:
    m, t = small()
    a, b, c = m.input("a", t), m.input("b", t), m.input("c", t)
    minus_a = -a
    cases = {
        "neg_product": -(a * b),
        "product_of_neg": -a * b,
        "right_sub": a - (b - c),
        "left_sub": (a - b) - c,
        "right_sum": a - (b + c),
        "right_div": a / (b * c),
        "left_sum_times": (a + b) * c,
        "double_neg": -minus_a,
        "negative_literal": a * -5,
        "min_max": maximum(minimum(a, b), c) + 1,
        "decimal": a * 0.1 + 1e-5,
    }
    for name, body in cases.items():
        m.vector(name, t).define(body)
    data = {"a": [1.0], "b": [2.0], "c": [3.0]}
    got = {name: formula(m, data, name) for name in cases}
    assert got == {
        "neg_product": "=-(B2*B3)",
        "product_of_neg": "=-B2*B3",
        "right_sub": "=B2-(B3-B4)",
        "left_sub": "=B2-B3-B4",
        "right_sum": "=B2-(B3+B4)",
        "right_div": "=B2/(B3*B4)",
        "left_sum_times": "=(B2+B3)*B4",
        "double_neg": "=-(-B2)",
        "negative_literal": "=B2*(-5)",
        "min_max": "=MAX(MIN(B2,B3),B4)+1",
        "decimal": "=B2*0.1+1E-05",
    }


def test_formulas_reference_the_same_period_and_share_the_lag_edge() -> None:
    result = export(
        debt_schedule.build().unwrap(),
        debt_schedule.data(),
        layout=debt_schedule.layout(),
    ).unwrap()
    cells = cells_of(result.yup)
    # Rows: 2 principal, 3 scheduled, 4 opening, 5 payment, 6 closing.
    assert cells[(4, 2)][0] == "=$B$2"  # opening[0] is the principal: points at it
    assert cells[(4, 3)][0] == "=B6"  # opening[1] is closing[0]: points at it
    assert cells[(6, 3)][0] == "=C4-C5"  # both operands from the period-1 column
    assert cells[(5, 3)][0] == "=MIN(C3,C4)"
    # opening[0] holds the principal's value, but the equation names opening: B4, not B2.
    assert cells[(5, 2)][0] == "=MIN(B3,B4)"


def test_a_copy_links_to_the_cell_it_copies() -> None:
    m, t = small()
    k = m.input("k", scalar)
    a = m.input("a", t)
    b, c, stretched = m.vectors(t, "b", "c", "stretched")
    b.define(a)
    c.define(b)
    stretched.define(k)
    result = export(m, {"k": [2.0], "a": [1.0, 3.0]}).unwrap()
    cells = cells_of(result.yup)
    # Rows: 2 k, 3 a, 4 b, 5 c, 6 stretched.
    assert [cells[(row, 3)][0] for row in (4, 5, 6)] == ["=C3", "=C4", "=$B$2"]
    total = m.vector("total", scalar)
    total.define(last(c))
    cells = cells_of(export(m, {"k": [2.0], "a": [1.0, 3.0]}).unwrap().yup)
    assert cells[(7, 2)][0] == "=C5"  # the last of c, not the input c copies


def test_every_formula_refers_only_to_earlier_lines() -> None:
    result = export(
        three_statement.build().unwrap(),
        three_statement.data(),
        layout=three_statement.layout(),
    ).unwrap()
    written: set[str] = set()
    import re

    from ukumari.yup import column_letters

    for line in result.yup.splitlines()[2:]:
        _, row, col, cell, _ = line.split("\t")
        if cell.startswith("="):
            for ref in re.findall(r"[A-Z]+[0-9]+", cell):
                assert ref in written, (line, ref)
        written.add(f"{column_letters(int(col))}{row}")


def test_formats_indents_and_widths() -> None:
    result = export(
        three_statement.build().unwrap(),
        three_statement.data(),
        layout=three_statement.layout(),
    ).unwrap()
    lines = result.yup.splitlines()
    assert "\n".join(lines[:2]) + "\n" == PREAMBLE
    first_of_column: dict[str, str] = {}
    for line in lines[2:]:
        _, _, col, _, fmt = line.split("\t")
        first_of_column.setdefault(col, fmt)
    assert first_of_column["1"] == "columnwidth=34"
    assert all(
        fmt.startswith("columnwidth=10")
        for c, fmt in first_of_column.items()
        if c != "1"
    )
    cells = cells_of(result.yup)
    row_of = {r.label: r.number for r in result.grid.rows}
    assert cells[(row_of["Revenue growth"], 1)] == ("$Revenue growth", "indent=1")
    assert cells[(row_of["Cost of sales"], 3)][1] == "numberformat=#,##0.0;(#,##0.0)"
    assert cells[(row_of["Balance check"], 3)][1] == ""  # General, deliberately
    assert cells[(row_of["Year"], 2)] == ("#2025.0", "numberformat=0")
    assert cells[(row_of["Tax, % of profit before tax"], 2)][1] == "numberformat=0.0%"


def test_an_error_input_is_written_as_na() -> None:
    m, t = small()
    a = m.input("a", t)
    m.vector("b", t).define(a * 2)
    result = export(m, {"a": [math.inf, 1.0]}).unwrap()
    cells = cells_of(result.yup)
    assert cells[(2, 2)][0] == "=NA()"
    assert "Model,2,2,16,#N/A" in result.values_csv
    assert "Model,3,2,16,#N/A" in result.values_csv
    assert "Model,3,3,1,2.0" in result.values_csv


def test_the_values_csv_lists_every_cell_in_the_same_order() -> None:
    result = export(
        three_statement.build().unwrap(),
        three_statement.data(),
        layout=three_statement.layout(),
    ).unwrap()
    yup_cells = [line.split("\t")[:3] for line in result.yup.splitlines()[2:]]
    values = [line.split(",")[:3] for line in result.values_csv.splitlines()[1:]]
    assert yup_cells == values


def test_a_scalar_sits_in_the_first_period_column() -> None:
    m, t = small()
    k = m.input("k", scalar)
    x = m.input("x", t)
    y = m.vector("y", t)
    y.define(lag(y, seed=k) + x)
    total = m.vector("total", scalar)
    total.define(last(y) * 2)
    result = export(m, {"k": [1.0], "x": [1.0, 2.0, 3.0]}).unwrap()
    assert result.grid.address("k", None) == Address("Model", 2, 2)
    assert result.grid.address("total", None) == Address("Model", 5, 2)
    assert cells_of(result.yup)[(5, 2)][0] == "=D4*2"


def test_first_links_to_the_first_cell() -> None:
    m, t = small()
    x = m.input("x", t[1:])
    ratio = m.vector("ratio", scalar)
    ratio.define(last(x) / first(x))
    result = export(m, {"x": [2.0, 3.0, 5.0]}).unwrap()
    assert cells_of(result.yup)[(3, 2)][0] == "=E2/C2"
    assert result.values[("ratio", None)] == 2.5


def test_the_export_refuses_when_p_is_one_ulp_out() -> None:
    circuit = three_statement.build().unwrap()
    real = load(emit(circuit))

    def nudged(inputs, extents=None, outputs=None):
        out = real.run(inputs, extents, outputs)
        out["net_income"][0, 2] = np.nextafter(out["net_income"][0, 2], np.inf)
        return out

    fake = ModuleType("nudged")
    fake.__dict__["run"] = nudged
    with pytest.raises(AssertionError, match="'net_income'\\[3\\]"):
        export(circuit, three_statement.data(), program=fake)


def test_a_layout_mistake_is_a_value_error() -> None:
    m, t = small()
    k1, k2 = m.input("k1", scalar), m.input("k2", scalar)
    m.vector("y", t).define(k1 + k2)
    with pytest.raises(ValueError, match="overlap"):
        export(
            m, {"k1": [1.0], "k2": [2.0]}, {"t": 2}, Layout(rows={"both": ("k1", "k2")})
        )
    with pytest.raises(ValueError, match="not declared"):
        export(m, {"k1": [1.0], "k2": [2.0]}, {"t": 2}, Layout(rows={"x": ("nope",)}))


def test_a_file_the_reader_refuses_comes_back_as_errors() -> None:
    m, t = small()
    m.input("bad\u0001name", t)
    match export(m, {"bad\u0001name": [1.0]}):
        case Err(errors):
            assert all(isinstance(e, YupError) for e in errors)
        case _:
            raise AssertionError("expected the read-back to refuse a control character")


def test_the_workbook_is_deterministic_and_well_formed() -> None:
    import io
    import zipfile
    from xml.dom.minidom import parseString

    result = export(
        three_statement.build().unwrap(),
        three_statement.data(),
        layout=three_statement.layout(),
    ).unwrap()
    workbook = result.xlsx().unwrap()
    assert workbook == result.xlsx().unwrap()
    archive = zipfile.ZipFile(io.BytesIO(workbook))
    names = [info.filename for info in archive.infolist()]
    assert names[0] == "[Content_Types].xml"
    assert "xl/calcChain.xml" not in names
    for name in names:
        parseString(archive.read(name))
    sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert '<col min="1" max="1" width="34.7109375" customWidth="1"/>' in sheet
    assert "<f>C14*(1+D3)</f>" in sheet
    styles = archive.read("xl/styles.xml").decode()
    assert r'formatCode="#,##0.0;\(#,##0.0\)"' in styles
