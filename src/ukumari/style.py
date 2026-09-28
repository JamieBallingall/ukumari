"""How a laid-out model looks: styles for its rows and cells, and views of its sheets.

A style is a handful of the cell keys of yupana's ``.yup`` format, and writes out as
exactly those keys: nothing is looked up when the workbook opens. A row's style applies
to its label and its values, and its fill and lines run across the empty cells of the
row too, so a total's line spans the table. Styles are for the reader, never the
arithmetic, and a layout without any writes no formatting but its number formats, indents
and widths.

>>> (TOTAL | Style(fill="FFF2CC")).pairs()
['bold=true', 'fill=FFF2CC', 'bordertop=thin']
>>> INPUT.pairs(), View(gridlines=False, freeze_rows=1).pairs()
(['fontcolor=0000FF'], ['gridlines=false', 'freezerows=1'])
"""

from dataclasses import dataclass, fields
from typing import Any

from yupana import HorizontalAlignment, LineStyle, Underline


def _written(key: str, value: object) -> str:
    """A key and value as a ``.yup`` format pair: a flag is ``true`` or ``false``."""
    if isinstance(value, bool):
        return f"{key}={'true' if value else 'false'}"
    return f"{key}={value}"


@dataclass(frozen=True, slots=True)
class Style:
    """How a cell looks, key by key; ``None`` leaves a key to the spreadsheet app. A
    colour is ``RRGGBB``, as in yupana's format."""

    bold: bool | None = None
    italic: bool | None = None
    underline: Underline | None = None
    font_color: str | None = None
    fill: str | None = None
    border_top: LineStyle | None = None
    border_bottom: LineStyle | None = None
    halign: HorizontalAlignment | None = None

    def __or__(self, other: Style) -> Style:
        """Both styles, ``other`` winning wherever both set a key."""
        merged: dict[str, Any] = {}
        for field in fields(self):
            mine, theirs = getattr(self, field.name), getattr(other, field.name)
            merged[field.name] = mine if theirs is None else theirs
        return Style(**merged)

    def pairs(self) -> list[str]:
        """The style's ``.yup`` format pairs, in the order the specification lists them."""
        keys = (
            ("bold", self.bold),
            ("italic", self.italic),
            ("underline", self.underline),
            ("fontcolor", self.font_color),
            ("fill", self.fill),
            ("bordertop", self.border_top),
            ("borderbottom", self.border_bottom),
            ("halign", self.halign),
        )
        return [_written(key, value) for key, value in keys if value is not None]

    def across(self) -> Style:
        """What of the style shows on an empty cell: its fill and its lines."""
        return Style(
            fill=self.fill, border_top=self.border_top, border_bottom=self.border_bottom
        )


@dataclass(frozen=True, slots=True)
class View:
    """How a sheet is shown: its gridlines, zoom and tab colour, and how many rows at
    the top and columns at the left stay in view as it scrolls. ``None`` and 0 leave the
    spreadsheet app's default."""

    gridlines: bool | None = None
    zoom: int | None = None
    tab_color: str | None = None
    freeze_rows: int = 0
    freeze_columns: int = 0

    def pairs(self) -> list[str]:
        """The view's ``.yup`` format pairs, for the sheet's ``!`` line."""
        keys = (
            ("gridlines", self.gridlines),
            ("zoom", self.zoom),
            ("tabcolor", self.tab_color),
            ("freezerows", self.freeze_rows or None),
            ("freezecolumns", self.freeze_columns or None),
        )
        return [_written(key, value) for key, value in keys if value is not None]


HEADING = Style(bold=True)
"""The title of a section."""
TOTAL = Style(bold=True, border_top=LineStyle.THIN)
"""A total: bold, under a line."""
GRAND_TOTAL = Style(
    bold=True, border_top=LineStyle.THIN, border_bottom=LineStyle.DOUBLE
)
"""A total of totals: bold, between a line above and a double line below."""
INPUT = Style(font_color="0000FF")
"""A number typed in rather than computed: blue, as modellers mark them."""
