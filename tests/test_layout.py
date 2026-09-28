"""The layout over several sheets: headings, blank rows, columns, and links across sheets."""

import pytest

from ukumari import Blank, Heading, Line, Model, Sheet, Workbook, lag, last, scalar
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
