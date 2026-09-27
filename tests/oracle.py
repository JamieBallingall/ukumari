"""yupana's oracle, run as an external command, for the tests that have the app check a file.

ukumari never imports the oracle: it needs Windows and the spreadsheet app, and running it
syncs ``../yupana``'s own environment, so those tests are opt-in.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

YUPANA = Path(__file__).resolve().parents[2] / "yupana"
needs_the_app = pytest.mark.skipif(
    sys.platform != "win32"
    or os.environ.get("UKUMARI_APP_TESTS") != "1"
    or not YUPANA.exists(),
    reason="needs Windows, the spreadsheet app, ../yupana, and UKUMARI_APP_TESTS=1",
)


def oracle(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run yupana's oracle as an external command; ukumari never imports it."""
    command = [
        "uv",
        "run",
        "--directory",
        str(YUPANA),
        "--package",
        "yupana-xlsx-oracle",
        "yupana-xlsx-oracle",
        *arguments,
    ]
    return subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", check=False
    )
