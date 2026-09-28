"""The README's code sample runs."""

import contextlib
import io
import re
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"


def test_the_readme_sample_runs() -> None:
    text = README.read_text(encoding="utf-8")
    (sample,) = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        exec(compile(sample, "README.md", "exec"), {})  # noqa: S102
    assert "[[70. 40. 10.  0.  0.]]" in printed.getvalue()
    assert "=\tMIN(C3,C4)" in printed.getvalue()
