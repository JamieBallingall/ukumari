"""Model inputs as CSV.

- The header is ``input,position,value``.
- ``position`` is 0-based within the input.
- ``value`` is a number in JSON's grammar.
- Every input's positions run from 0 with no gaps or repeats; a single-value input has only
  position 0.

>>> read_inputs("input,position,value\\ngrowth,1,0.07\\ngrowth,0,0.08\\ntax,0,0.25\\n")
Ok(value={'growth': (0.08, 0.07), 'tax': (0.25,)})
"""

import csv
import io
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from yupana.result import Err, Ok, Result

HEADER = ["input", "position", "value"]
_POSITION = re.compile(r"0|[1-9][0-9]*")
_NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?")


@dataclass(frozen=True, slots=True)
class CsvError:
    """A problem in an inputs CSV, at a 1-based line (0 for the file as a whole)."""

    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}" if self.line else self.message


def read_inputs(
    text: str,
) -> Result[dict[str, tuple[float, ...]], tuple[CsvError, ...]]:
    """Every input's values, or every problem in the file at once."""
    errors: list[CsvError] = []
    rows = csv.reader(io.StringIO(text, newline=""))
    header = next(rows, None)
    if header != HEADER:
        return Err((CsvError(1, f"the header must be {','.join(HEADER)}"),))
    found: dict[str, dict[int, tuple[int, float]]] = {}
    for fields in rows:
        line = rows.line_num
        if len(fields) != 3:
            errors.append(CsvError(line, f"needs 3 fields, not {len(fields)}"))
            continue
        name, position, value = fields
        ok = True
        if not name:
            errors.append(CsvError(line, "the input name is empty"))
            ok = False
        if not _POSITION.fullmatch(position):
            errors.append(
                CsvError(
                    line, f"position must be a whole number from 0, not {position!r}"
                )
            )
            ok = False
        if not _NUMBER.fullmatch(value):
            errors.append(CsvError(line, f"value must be a number, not {value!r}"))
            ok = False
        if not ok:
            continue
        seen = found.setdefault(name, {})
        index = int(position)
        if index in seen:
            earlier = seen[index][0]
            errors.append(
                CsvError(line, f"{name!r} position {index} repeats line {earlier}")
            )
            continue
        seen[index] = (line, float(value))
    for name, seen in found.items():
        missing = sorted(set(range(max(seen) + 1)) - seen.keys())
        if missing:
            shown = ", ".join(str(m) for m in missing[:5])
            errors.append(CsvError(0, f"{name!r} has no value at position {shown}"))
    if errors:
        return Err(tuple(errors))
    return Ok(
        {
            name: tuple(seen[i][1] for i in range(len(seen)))
            for name, seen in found.items()
        }
    )


def write_inputs(data: Mapping[str, Sequence[float]]) -> str:
    """Inputs as CSV, each value the shortest text that reads back as the same double.

    The error value cannot be written: JSON's grammar has no NaN.
    """
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    for name, values in data.items():
        for position, value in enumerate(values):
            x = float(value)
            if not math.isfinite(x):
                raise ValueError(
                    f"{name!r}[{position}] is {x!r}, which CSV cannot hold"
                )
            text = repr(x)
            writer.writerow([name, position, text])
    return out.getvalue()
