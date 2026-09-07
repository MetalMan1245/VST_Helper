# tests/integration/conftest.py
"""Shared integration fixtures: runner resolution, VST_HELPER_TEST_WINE pin."""
import os
import shutil
import pytest
from pathlib import Path

from vst_helper.config import Runner

@pytest.fixture
def runner() -> Runner:
    """VST_HELPER_TEST_WINE pin wins, then Heroic, then system wine."""
    wine = os.environ.get("VST_HELPER_TEST_WINE")
    if wine:
        p = Path(wine).expanduser()
        if not p.is_file():
            pytest.fail(f"VST_HELPER_TEST_WINE points at a missing binary: {p}")
        return Runner(name="integration", path=p)

    found = sorted(Path("~/.config/heroic/tools/wine").expanduser()
                   .glob("*/bin/wine"))
    if found:
        return Runner(name="integration", path=found[0])

    system = shutil.which("wine")
    if system:
        return Runner(name="integration", path=Path(system))

    pytest.skip("No Wine found — install one or set VST_HELPER_TEST_WINE")
