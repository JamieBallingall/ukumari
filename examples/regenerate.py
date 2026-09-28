"""Rewrite the files committed in ``expected/``, after a deliberate change.

The tests check that these files match what the code writes now, so a change to the
examples, the writer or the format shows up as a failing test and then as a readable diff.
"""

from pathlib import Path

import debt_schedule
import quarterly
import three_statement


def main() -> None:
    expected = Path(__file__).resolve().parent / "expected"
    for example in (debt_schedule, three_statement, quarterly):
        for name, text in example.outputs().items():
            (expected / name).write_text(text, encoding="utf-8", newline="")
            print(f"wrote {expected / name}")


if __name__ == "__main__":
    main()
