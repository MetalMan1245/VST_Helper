# tests/test_plugin_installer.py
import pytest
from pathlib import Path

from vst_helper.plugin_installer import (
    install_portable, find_installed_plugins, InstallError,
)

@pytest.fixture
def fake_prefix(tmp_path):
    (tmp_path / "drive_c").mkdir()
    (tmp_path / "system.reg").write_text("")
    return tmp_path

def test_portable_vst3_bundle_copies_into_prefix(fake_prefix, tmp_path):
    # .vst3 is a directory bundle
    src = tmp_path / "Test Plugin.vst3"
    (src / "Contents" / "x86_64-win").mkdir(parents=True)
    (src / "Contents" / "x86_64-win" / "Test Plugin.vst3").write_text("binary")

    dest = install_portable(None, fake_prefix, src, "vst3")
    assert dest == (fake_prefix / "drive_c" / "Program Files" /
                    "Common Files" / "VST3" / "Test Plugin.vst3")
    assert (dest / "Contents" / "x86_64-win" / "Test Plugin.vst3").is_file()

def test_find_detects_installed_vst3(fake_prefix, tmp_path):
    src = tmp_path / "Test Plugin.vst3"
    (src / "Contents").mkdir(parents=True)
    install_portable(None, fake_path := fake_prefix, src, "vst3")
    assert find_installed_plugins(fake_path, "vst3") == [
        fake_path / "drive_c" / "Program Files" / "Common Files" / "VST3" / "Test Plugin.vst3"
    ]

def test_portable_rejects_unknown_format(fake_prefix, tmp_path):
    src = tmp_path / "thing.exe"
    src.write_text("x")
    with pytest.raises(InstallError, match="Unknown plugin format"):
        install_portable(None, fake_prefix, src, "aax")

def test_portable_rejects_missing_source(fake_prefix):
    with pytest.raises(InstallError, match="not found"):
        install_portable(None, fake_prefix, Path("/nonexistent.vst3"), "vst3")

def test_overwrite_replaces_old_bundle(fake_prefix, tmp_path):
    src = tmp_path / "P.vst3"
    (src / "Contents").mkdir(parents=True)
    install_portable(None, fake_prefix, src, "vst3")
    (src / "Contents" / "new.marker").write_text("")
    install_portable(None, fake_prefix, src, "vst3")  # overwrite path
    assert (fake_prefix / "drive_c" / "Program Files" / "Common Files" /
            "VST3" / "P.vst3" / "Contents" / "new.marker").is_file()
