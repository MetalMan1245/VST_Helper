# tests/test_discovery.py
import stat
import pytest
from pathlib import Path

from vst_helper.discovery import discover
from vst_helper.config import ConfigError

FAKE_WINE = """\
#!/bin/sh
echo "wine-9.21 (Staging)"
"""


def _make_fake_wine(root, dirname, works=True):
    d = root / dirname
    (d / "bin").mkdir(parents=True)
    script = d / "bin" / "wine"
    script.write_text("#!/bin/sh\necho 'wine-9.21 (Staging)'\n")
    script.chmod(0o755)
    return script


def test_discovers_heroic_shaped_install(tmp_path):
    _make_fake_wine(tmp_path, "wine-9.21-staging-amd64")
    found = discover([tmp_path])
    assert [r.name for r in found] == ["wine-9.21-staging-amd64"]
    assert found[0].bindir == tmp_path / "wine-9.21-staging-amd64" / "bin"


def test_skips_broken_wine_without_failing(tmp_path):
    d = tmp_path / "broken"
    (d / "bin").mkdir(parents=True)
    (d / "bin" / "wine").write_text("#!/bin/sh\nexit 1\n")
    (d / "bin" / "wine").chmod(0o755)
    assert discover([tmp_path]) == []


def test_ignores_directories_without_a_wine_binary(tmp_path):
    (tmp_path / "not-wine" / "bin").mkdir(parents=True)
    (tmp_path / "not-wine" / "bin" / "other").write_text("")
    assert discover([tmp_path]) == []


def test_missing_search_root_is_harmless(tmp_path):
    assert discover([tmp_path / "nope"]) == []
