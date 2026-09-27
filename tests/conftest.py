"""The mock audio fixtures are gitignored (`*.wav`), so a fresh clone has none.

They are regenerable by construction, so regenerate them rather than committing binaries
or making the manifest validator lenient about missing audio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = ROOT / "eval" / "datasets" / "mock"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session", autouse=True)
def mock_audio_fixtures() -> None:
    expected = [
        MOCK_DIR / json.loads(line)["audio"]
        for line in (MOCK_DIR / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if all(p.exists() for p in expected):
        return
    sys.path.insert(0, str(MOCK_DIR))
    import make_fixtures  # type: ignore[import-not-found]

    make_fixtures.main()
