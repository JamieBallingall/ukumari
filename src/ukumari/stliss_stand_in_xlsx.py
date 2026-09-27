"""A throwaway xlsx writer, standing in for ``stliss``'s until it exists.

It implements enough of ``01-stliss.md``'s writer to open the examples' workbooks: sheets,
numbers, text, logicals and formulas with no cached values, number formats, indents and
column widths. It refuses a number format it cannot spell as the app would, rather than
guess. **Delete it once ``stliss`` exists.** It has never been checked against the app.
"""

import io
import math
import re
import zipfile

from ukumari.stliss_stand_in import SlsCell

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_SHEETML = "application/vnd.openxmlformats-officedocument.spreadsheetml"
_RELS_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_BUILT_IN = {
    "general": 0,
    "0": 1,
    "0.00": 2,
    "#,##0": 3,
    "#,##0.00": 4,
    "0%": 9,
    "0.00%": 10,
    "0.00e+00": 11,
    "# ?/?": 12,
    "# ??/??": 13,
    "#,##0_);(#,##0)": 37,
    "#,##0_);[red](#,##0)": 38,
    "#,##0.00_);(#,##0.00)": 39,
    "#,##0.00_);[red](#,##0.00)": 40,
    "##0.0e+0": 48,
    "@": 49,
}
_ESCAPE_SHAPE = re.compile(r"_x[0-9A-Fa-f]{4}_")


def _xml(text: str, attribute: bool = False) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace('"', "&quot;") if attribute else text


def canonical_format(code: str) -> str:
    """A custom number-format code in the app's canonical spelling, for simple codes.

    A literal ``-``, space, ``(``, ``)`` or non-thousands ``,`` is backslash-escaped;
    quoted text, bracketed parts, and the character after ``_``, ``*`` or a backslash are
    kept. Any other letter is refused.

    >>> canonical_format("#,##0.0;(#,##0.0)"), canonical_format("0.0%")
    ('#,##0.0;\\\\(#,##0.0\\\\)', '0.0%')
    """
    out: list[str] = []
    i = 0
    while i < len(code):
        c = code[i]
        if c in '"[':
            end = code.index('"' if c == '"' else "]", i + 1)
            out.append(code[i : end + 1])
            i = end + 1
            continue
        if c in "_*\\":
            out.append(code[i : i + 2])
            i += 2
            continue
        if c == ",":
            before = code[i - 1] if i else ""
            after = code[i + 1] if i + 1 < len(code) else ""
            thousands = before in "#0?" and after in "#0?" and before and after
            out.append(c if thousands else "\\,")
        elif c in "-() ":
            out.append("\\" + c)
        elif c.isalpha() and code[i : i + 2] not in ("E+", "E-"):
            raise ValueError(f"the stand-in writer cannot write the format {code!r}")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def column_width(width: float) -> float:
    """The stored width for a width in characters, with a maximum digit width of 7.

    >>> column_width(10), column_width(0.5), column_width(34)
    (10.7109375, 0.85546875, 34.7109375)
    """
    if width >= 1:
        pixels = math.trunc(width * 7 + 0.5) + 5
    else:
        pixels = math.trunc(width * 12 + 0.5)
    return math.trunc(pixels * 256 / 7) / 256


def _letters(column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _cell_xml(cell: SlsCell, style: int, strings: dict[str, int]) -> str:
    where = f'r="{_letters(cell.col)}{cell.row}"' + (f' s="{style}"' if style else "")
    kind, rest = cell.cell[0], cell.cell[1:]
    match kind:
        case "=":
            return f"<c {where}><f>{_xml(rest)}</f></c>"
        case "#":
            return f"<c {where}><v>{float(rest)!r}</v></c>"
        case "?":
            return f'<c {where} t="b"><v>{1 if rest == "TRUE" else 0}</v></c>'
        case _:
            index = strings.setdefault(rest, len(strings))
            return f'<c {where} t="s"><v>{index}</v></c>'


def _cols(widths: list[tuple[int, float]]) -> str:
    merged: list[tuple[int, int, float]] = []
    for col, width in sorted(widths):
        if merged and merged[-1][1] == col - 1 and merged[-1][2] == width:
            merged[-1] = (merged[-1][0], col, width)
        else:
            merged.append((col, col, width))
    if not merged:
        return ""
    items = []
    for first, last, width in merged:
        if width == 0:
            items.append(
                f'<col min="{first}" max="{last}" width="0" hidden="1" customWidth="1"/>'
            )
        else:
            stored = column_width(width)
            items.append(
                f'<col min="{first}" max="{last}" width="{stored!r}" customWidth="1"/>'
            )
    return "<cols>" + "".join(items) + "</cols>"


def _styles(custom: dict[str, int], styles: dict[tuple[int, int], int]) -> str:
    num_fmts = ""
    if custom:
        entries = "".join(
            f'<numFmt numFmtId="{number}" formatCode="{_xml(code, True)}"/>'
            for code, number in custom.items()
        )
        num_fmts = f'<numFmts count="{len(custom)}">{entries}</numFmts>'
    xfs = []
    for number, indent in styles:
        attributes = f'numFmtId="{number}" fontId="0" fillId="0" borderId="0" xfId="0"'
        if number:
            attributes += ' applyNumberFormat="1"'
        if indent:
            xfs.append(
                f'<xf {attributes} applyAlignment="1">'
                f'<alignment horizontal="left" indent="{indent}"/></xf>'
            )
        else:
            xfs.append(f"<xf {attributes}/>")
    return (
        f'<styleSheet xmlns="{_MAIN}">{num_fmts}'
        '<fonts count="1"><font><sz val="11"/><color rgb="FF000000"/>'
        '<name val="Aptos Narrow"/><family val="2"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/>'
        "</border></borders>"
        '<cellStyleXfs count="1">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>'
        "</cellStyles></styleSheet>"
    )


def write_xlsx(cells: tuple[SlsCell, ...]) -> bytes:
    """An xlsx holding the cells read from an ``.sls`` file. The output is deterministic."""
    sheets = list(dict.fromkeys(c.sheet for c in cells))
    strings: dict[str, int] = {}
    custom: dict[str, int] = {}
    styles: dict[tuple[int, int], int] = {(0, 0): 0}
    rows: dict[str, dict[int, list[tuple[int, str]]]] = {s: {} for s in sheets}
    widths: dict[str, list[tuple[int, float]]] = {s: [] for s in sheets}
    text_cells = 0

    for cell in cells:
        code = cell.format.get("numberformat")
        number = 0
        if code is not None:
            number = _BUILT_IN.get(code.casefold(), -1)
            if number < 0:
                canonical = canonical_format(code)
                number = custom.setdefault(canonical, 164 + len(custom))
        key = (number, int(cell.format.get("indent", "0")))
        style = styles.setdefault(key, len(styles))
        given = cell.format.get("columnwidth")
        if given is not None and given != "default":
            widths[cell.sheet].append((cell.col, float(given)))
        text_cells += cell.cell.startswith("$")
        xml = _cell_xml(cell, style, strings)
        rows[cell.sheet].setdefault(cell.row, []).append((cell.col, xml))

    overrides = [("/xl/workbook.xml", f"{_SHEETML}.sheet.main+xml")]
    overrides += [
        (f"/xl/worksheets/sheet{i}.xml", f"{_SHEETML}.worksheet+xml")
        for i in range(1, len(sheets) + 1)
    ]
    overrides.append(("/xl/styles.xml", f"{_SHEETML}.styles+xml"))
    if strings:
        overrides.append(("/xl/sharedStrings.xml", f"{_SHEETML}.sharedStrings+xml"))
    content_types = (
        f'<Types xmlns="{_TYPES}">'
        f'<Default Extension="rels" ContentType="{_RELS_TYPE}"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + "".join(
            f'<Override PartName="{name}" ContentType="{kind}"/>'
            for name, kind in overrides
        )
        + "</Types>"
    )
    package_rels = (
        f'<Relationships xmlns="{_PACKAGE_REL}">'
        f'<Relationship Id="rId1" Type="{_REL}/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    workbook = (
        f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets>'
        + "".join(
            f'<sheet name="{_xml(sheet, True)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, sheet in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    targets = [
        ("worksheet", f"worksheets/sheet{i}.xml") for i in range(1, len(sheets) + 1)
    ]
    targets.append(("styles", "styles.xml"))
    if strings:
        targets.append(("sharedStrings", "sharedStrings.xml"))
    workbook_rels = (
        f'<Relationships xmlns="{_PACKAGE_REL}">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{_REL}/{kind}" Target="{target}"/>'
            for i, (kind, target) in enumerate(targets, start=1)
        )
        + "</Relationships>"
    )
    parts = [
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", package_rels),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", workbook_rels),
    ]
    for number, sheet in enumerate(sheets, start=1):
        found = rows[sheet]
        columns = [col for row in found.values() for col, _ in row]
        dimension = (
            f"{_letters(min(columns))}{min(found)}:{_letters(max(columns))}{max(found)}"
        )
        data = "".join(
            f'<row r="{r}">' + "".join(xml for _, xml in sorted(found[r])) + "</row>"
            for r in sorted(found)
        )
        selected = ' tabSelected="1"' if number == 1 else ""
        worksheet = (
            f'<worksheet xmlns="{_MAIN}" xmlns:r="{_REL}">'
            f'<dimension ref="{dimension}"/>'
            f'<sheetViews><sheetView{selected} workbookViewId="0"/></sheetViews>'
            '<sheetFormatPr defaultRowHeight="15"/>'
            f"{_cols(widths[sheet])}<sheetData>{data}</sheetData>"
            '<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" '
            'header="0.3" footer="0.3"/></worksheet>'
        )
        parts.append((f"xl/worksheets/sheet{number}.xml", worksheet))
    parts.append(("xl/styles.xml", _styles(custom, styles)))
    if strings:

        def shared(text: str) -> str:
            text = _ESCAPE_SHAPE.sub(lambda m: "_x005F" + m.group(0), text)
            space = ' xml:space="preserve"' if text != text.strip() else ""
            return f"<si><t{space}>{_xml(text)}</t></si>"

        parts.append(
            (
                "xl/sharedStrings.xml",
                f'<sst xmlns="{_MAIN}" count="{text_cells}" '
                f'uniqueCount="{len(strings)}">'
                + "".join(shared(text) for text in strings)
                + "</sst>",
            )
        )

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, xml in parts:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            archive.writestr(info, (_DECLARATION + xml).encode("utf-8"))
    return out.getvalue()
