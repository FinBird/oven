from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]
project_root_str = str(PROJECT_ROOT)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return PROJECT_ROOT / "fixtures" / "abc"
