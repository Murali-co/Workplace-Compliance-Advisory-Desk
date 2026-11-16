"""Run the consolidated backend test suite from any working directory."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    raise SystemExit(
        subprocess.call(
            [sys.executable, "-m", "pytest", "-c", str(ROOT / "tests/pytest.ini"), *sys.argv[1:]],
            cwd=ROOT,
        )
    )
