"""The layout over several sheets: headings, blank rows, columns, and links across sheets."""

from dataclasses import replace

import pytest
from yupana import LineStyle

from ukumari import (
    GRAND_TOTAL,
    HEADING,
    INPUT,
    TOTAL,
    Blank,
    Heading,
    Layout,
    Line,
    Model,
    Sheet,
    Style,
    View,
    Workbook,
    lag,
    last,
    scalar,
)
from ukumari.layout import Address
from ukumari.pipeline import Export, export


def cells_of(result: Export) -> dict[tuple[str, int, int], tuple[str, str]]:
    """(sheet, row, col) → (type and cell, format), for the cells in ``.yup`` text."""
    found = {}
    for line in result.yup.splitlines()[2:]:
        sheet, row, col, kind, cell, fmt = line.split("\t")
        if kind in ("=", "#", "$", "?", "."):
            found[(sheet, int(row), int(col))] = (kind + cell, fmt)
    return found


def widths_of(result: Export) -> dict[tuple[str, str], str]:
    """(sheet, col) → format, for the columns in ``.yup`` text, ``*`` for every one."""
    found = {}
    for line in result.yup.splitlines()[2:]:
        sheet, _, col, kind, _, fmt = line.split("\t")
        if kind == "|":
            found[(sheet, col)] = fmt
    return found


def two_regions() -> Model:
    """History and a forecast that rolls on from it, with a copy of the history on a sheet
    of its own, and a copy of the forecast's assumption on the forecast's sheet."""
    m = Model()
    history, forecast = m.region("history"), m.region("forecast")
    m.axis("quarter", history, forecast)
    m.input("date_history", history)
    m.input("date_forecast", forecast)
    sales = m.input("sales", history)
    growth = m.input("growth", forecast)
    tax_rate = m.input("tax_rate", scalar)
    tax_rate_stretched = m.vector("tax_rate_stretched", forecast)
    tax_rate_stretched.define(tax_rate)
    sales_copy = m.vector("sales_copy", history)
    sales_copy.define(sales)
    opening = m.vector("opening", scalar)
    opening.define(last(sales_copy))
    growth_here, tax_here, projected, tax = m.vectors(
        forecast, "growth_here", "tax_here", "projected", "tax"
    )
    growth_here.define(growth)
    tax_here.define(tax_rate_stretched)
    projected.define(lag(projected, seed=opening) * (1 + growth_here))
    tax.define(projected * tax_here)
    return m


def data() -> dict[str, list[float]]:
    return {
        "date_history": [46022.0, 46112.0],
        "date_forecast": [46203.0, 46295.0, 46387.0],
        "sales": [10.0, 12.0],
        "growth": [0.1, 0.2, 0.3],
        "tax_rate": [0.25],
    }


def workbook() -> Workbook:
    return Workbook(
        (
            Sheet(
                "Inputs",
                (
                    Line("Quarter", ("date_history", "date_forecast"), "mmm-yy"),
                    Blank(),
                    Heading("History"),
                    Line("Sales", ("sales",), indent=1),
                    Heading("Assumptions"),
                    Line("Growth", ("growth",), "0.0%"),
                    Line("Tax rate", ("tax_rate", "tax_rate_stretched"), "0.0%"),
                ),
                label_width=20,
                period_width=9,
            ),
            Sheet(
                "Actuals",
                (
                    Line("Quarter", ()),
                    Line("Sales", ("sales_copy",)),
                    Line("Opening", ("opening",)),
                ),
                start="history",
            ),
            Sheet(
                "Forecast",
                (
                    Line("Growth", ("growth_here",)),
                    Line("Tax rate", ("tax_here",)),
                    Blank(),
                    Line("Sales", ("projected",)),
                    Line("Tax", ("tax",)),
                ),
                start="forecast",
            ),
        )
    )


def test_each_sheet_starts_at_its_own_region() -> None:
    result = export(two_regions(), data(), layout=workbook()).unwrap()
    address = result.grid.address
    # Inputs starts at the axis's first position: history in C and D, the forecast after.
    assert address("date_history", 0) == Address("Inputs", 1, 3)
    assert address("date_forecast", 2) == Address("Inputs", 1, 5)
    # A single value is in column B, beside its stretched row.
    assert address("tax_rate", None) == Address("Inputs", 7, 2)
    assert address("tax_rate_stretched", 2) == Address("Inputs", 7, 5)
    # Actuals and Forecast each show their own region's first position in column C.
    assert address("sales_copy", 0) == Address("Actuals", 2, 3)
    assert address("projected", 2) == Address("Forecast", 4, 3)
    assert address("tax", 4) == Address("Forecast", 5, 5)


def test_headings_blank_rows_formats_and_widths() -> None:
    result = export(two_regions(), data(), layout=workbook()).unwrap()
    cells = cells_of(result)
    assert cells[("Inputs", 3, 1)] == ("$History", "")
    assert cells[("Inputs", 4, 1)] == ("$Sales", "indent=1")
    assert not any(sheet == "Inputs" and row == 2 for sheet, row, _ in cells)
    assert cells[("Inputs", 1, 3)] == ("#46022.0", "numberformat=mmm-yy")
    assert cells[("Actuals", 1, 1)] == ("$Quarter", "")
    # A sheet's period width is every column's, and its label width column A's; a sheet
    # that sets neither has no widths.
    assert widths_of(result) == {
        ("Inputs", "*"): "columnwidth=9",
        ("Inputs", "1"): "columnwidth=20",
    }
    # The sheets appear in the workbook in the layout's order.
    assert list(result.checked.sheets) == [
        "Inputs",
        "Actuals",
        "Forecast",
    ]


def test_copies_link_across_sheets_and_formulas_read_local_copies() -> None:
    result = export(two_regions(), data(), layout=workbook()).unwrap()
    cells = cells_of(result)
    # A stretched single value links to it; a copy on another sheet links to the same
    # quarter of the row it copies.
    assert cells[("Inputs", 7, 5)][0] == "=$B$7"
    assert cells[("Forecast", 2, 3)][0] == "='Inputs'!E7"
    assert cells[("Forecast", 1, 4)][0] == "='Inputs'!F6"
    assert cells[("Actuals", 2, 3)][0] == "='Inputs'!C4"
    # The last of the copy, not the input it copies.
    assert cells[("Actuals", 3, 2)][0] == "=D2"
    # The seed is the single value the model names; the rest reads this sheet's own copies.
    assert cells[("Forecast", 4, 3)][0] == "='Actuals'!$B$3*(1+C1)"
    assert cells[("Forecast", 4, 4)][0] == "=C4*(1+D1)"
    assert cells[("Forecast", 5, 5)][0] == "=E4*E2"
    assert result.xlsx().is_ok()


def test_mistakes_in_a_workbook_are_all_named() -> None:
    wrong = Workbook(
        (
            Sheet(
                "Forecast",
                (
                    Line("Sales", ("projected", "sales")),
                    Line("Both", ("tax_rate", "opening")),
                    Heading(""),
                ),
                start="forecast",
            ),
            Sheet("forecast", (Line("Growth", ("growth", "nothing")),), start="later"),
        )
    )
    with pytest.raises(ValueError) as caught:
        export(two_regions(), data(), layout=wrong)
    message = str(caught.value)
    for fragment in (
        "'sales' starts left of the first period column",
        "'tax_rate' and 'opening' would overlap in column B",
        "a row label must not be empty",
        "sheets 'Forecast' and 'forecast' are one sheet",
        "starts at 'later', which is not a region",
        "names 'nothing', which is not declared",
        "'tax' is on no sheet",
    ):
        assert fragment in message, fragment


def styled() -> Workbook:
    """The workbook above, dressed: a header row, a filled heading, a short blank row, a
    total and a grand total, inputs in blue, and a view on two sheets."""
    inputs, actuals, forecast = workbook().sheets
    header = Style(bold=True, border_bottom=LineStyle.THIN)
    return Workbook(
        (
            replace(
                inputs,
                items=(
                    Line("Quarter", ("date_history", "date_forecast"), "mmm-yy", None, header),
                    Blank(height=6),
                    Heading("History", HEADING | Style(fill="DDEBF7")),
                    Line("Sales", ("sales",), indent=1),
                    Heading("Assumptions"),
                    Line("Growth", ("growth",), "0.0%"),
                    Line("Tax rate", ("tax_rate", "tax_rate_stretched"), "0.0%"),
                ),
                view=View(gridlines=False, tab_color="0070C0", freeze_rows=1, freeze_columns=2),
            ),
            actuals,
            replace(
                forecast,
                items=(
                    *forecast.items[:3],
                    Line("Sales", ("projected",), style=TOTAL),
                    Line("Tax", ("tax",), style=GRAND_TOTAL),
                ),
                view=View(zoom=85),
            ),
        ),
        input_style=INPUT,
    )  # fmt: skip


def all_lines(result: Export) -> dict[tuple[str, str, str], tuple[str, str]]:
    """(sheet, row, col) → (type, format), for every line of ``.yup`` text after the
    header, the row or col ``*`` where the line has one."""
    found = {}
    for line in result.yup.splitlines()[2:]:
        sheet, row, col, kind, _, fmt = line.split("\t")
        found[(sheet, row, col)] = (kind, fmt)
    return found


def test_a_rows_style_goes_on_its_label_and_values_and_across_its_empty_cells() -> None:
    lines = all_lines(export(two_regions(), data(), layout=styled()).unwrap())
    header = "bold=true|borderbottom=thin"
    assert lines[("Inputs", "1", "1")] == ("$", header)
    # The dates are typed in, so they are blue as well; column B, empty, has the line.
    assert lines[("Inputs", "1", "3")] == (
        "#",
        "numberformat=mmm-yy|bold=true|fontcolor=0000FF|borderbottom=thin",
    )
    assert lines[("Inputs", "1", "2")] == (".", "borderbottom=thin")
    assert lines[("Inputs", "2", "*")] == ("-", "rowheight=6")
    assert lines[("Inputs", "3", "1")] == ("$", "bold=true|fill=DDEBF7")
    assert [lines[("Inputs", "3", str(col))] for col in range(2, 8)] == [
        (".", "fill=DDEBF7")
    ] * 6
    assert ("Inputs", "3", "8") not in lines, (
        "the fill stops at the sheet's last column"
    )
    assert ("Inputs", "5", "2") not in lines, "a heading without a style fills nothing"
    # A typed-in single value is blue; the row that links to it is not.
    assert lines[("Inputs", "7", "2")] == ("#", "numberformat=0.0%|fontcolor=0000FF")
    assert lines[("Inputs", "7", "5")] == ("=", "numberformat=0.0%")
    assert lines[("Forecast", "4", "1")] == ("$", "bold=true|bordertop=thin")
    assert lines[("Forecast", "4", "3")] == ("=", "bold=true|bordertop=thin")
    assert lines[("Forecast", "4", "2")] == (".", "bordertop=thin")
    assert lines[("Forecast", "5", "2")] == (".", "bordertop=thin|borderbottom=double")


def test_the_views_come_last() -> None:
    result = export(two_regions(), data(), layout=styled()).unwrap()
    assert result.yup.splitlines()[-2:] == [
        "Inputs\t*\t*\t!\t\tgridlines=false|tabcolor=0070C0|freezerows=1|freezecolumns=2",
        "Forecast\t*\t*\t!\t\tzoom=85",
    ]
    assert [v.sheet for v in result.checked.views] == ["Inputs", "Forecast"]


def test_the_styles_of_a_one_sheet_layout_name_its_rows() -> None:
    m = Model()
    t = m.region("t")
    m.axis("time", t)
    a = m.input("a", t)
    m.vector("b", t).define(a * 2)
    layout = Layout(
        rows={"A": ("a",), "B": ("b",)}, styles={"B": TOTAL}, input_style=INPUT
    )
    lines = all_lines(export(m, {"a": [1.0, 2.0]}, layout=layout).unwrap())
    assert lines[("Model", "2", "2")] == ("#", "fontcolor=0000FF")
    assert lines[("Model", "3", "3")] == ("=", "bold=true|bordertop=thin")
    with pytest.raises(ValueError, match="styles names row 'C', which is not in rows"):
        export(m, {"a": [1.0, 2.0]}, layout=replace(layout, styles={"C": TOTAL}))
