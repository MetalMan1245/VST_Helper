# tests/integration/test_prefix_integration.py
"""
Integration tests: these RUN REAL WINE. Slow (tens of seconds), touches
the filesystem for real. Excluded from the default suite; run explicitly.
"""
import os
import shutil
import pytest
from pathlib import Path

from vst_helper.config import Runner
from vst_helper.prefix_manager import (
    create_prefix, shutdown_prefix, delete_prefix, _is_initialized,
)

pytestmark = pytest.mark.integration

TEST_PREFIX_ROOT = Path(os.environ.get(
    "VST_HELPER_TEST_ROOT", "~/.local/share/vst-helper-test")).expanduser()

@pytest.fixture
def prefix_path(runner):
    path = TEST_PREFIX_ROOT / "it-pfx"
    yield path
    shutdown_prefix(runner, path)
    if path.exists():
        delete_prefix(path)

@pytest.mark.integration
def test_full_lifecycle(runner, prefix_path):
    create_prefix(runner, prefix_path)
    assert _is_initialized(prefix_path)
    # A second wineboot on an existing prefix must succeed (upgrade-in-place)
    create_prefix(runner, prefix_path)
    shutdown_prefix(runner, prefix_path)
    delete_prefix(prefix_path)
    assert not prefix_path.exists()
