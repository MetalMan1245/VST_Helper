# tests/test_prefix_manager.py
import pytest
from pathlib import Path

from vst_helper.config import Runner
from vst_helper.prefix_manager import (
    create_prefix, delete_prefix, PrefixOperationError,
)

def test_create_refuses_existing_non_prefix_dir(tmp_path):
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "somefile").write_text("precious user data")
    r = Runner(name="fake", path=tmp_path / "nowhere" / "wine")
    with pytest.raises(PrefixOperationError, match="refusing"):
        create_prefix(r, target)

def test_delete_refuses_non_prefix(tmp_path):
    target = tmp_path / "not-a-prefix"
    target.mkdir()
    with pytest.raises(PrefixOperationError):
        delete_prefix(target)
