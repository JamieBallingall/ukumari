"""Rewrite the files committed beside the examples, after a deliberate change.

The tests check that these files match what the code writes now, so a change to the
examples, the writer or the format shows up as a failing test and then as a readable diff.
"""

from pathlib import Path

import debt_schedule
import quarterly
import three_statement


def main() -> None:
    here = Path(__file__).resolve().parent
    for example in (debt_schedule, three_statement, quarterly):
        for name, text in example.outputs().items():
            (here / name).write_text(text, encoding="utf-8", newline="")
            print(f"wrote {here / name}")


if __name__ == "__main__":
    main()
