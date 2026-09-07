# tests/integration/test_plugin_integration.py
"""
Integration: real prefix + real yabridgectl against real plugin assets.
Assets live in ~/Dev/VST_Helper/test-assets/ (gitignored). Workflow per
test: create prefix -> install portable plugin -> add path -> bare sync
-> assert bridged .so appeared. Installer .exe path is interactive and
covered by scripts/manual_installer_test.py instead.
"""
import shutil
import pytest
from pathlib import Path

from vst_helper.prefix_manager import (
    create_prefix, shutdown_prefix, delete_prefix,
)
from vst_helper.plugin_installer import (
    install_portable, find_installed_plugins, add_sync_targets, sync_yabridge,
)

pytestmark = pytest.mark.integration

TEST_ROOT = Path("~/.local/share/vst-helper-test").expanduser()
ASSETS = Path("~/Dev/VST_Helper/test-assets").expanduser()

def _cleanup(runner, pfx):
    shutdown_prefix(runner, pfx)
    if (pfx / "drive_c").is_dir():
        delete_prefix(pfx)

@pytest.mark.integration
def test_portable_vst3s_install_and_sync(runner):
    if shutil.which("yabridgectl") is None:
        pytest.skip("yabridgectl not installed")
    assets = sorted(ASSETS.glob("*.vst3"))
    if not assets:
        pytest.skip("no .vst3 assets in test-assets/")

    pfx = TEST_ROOT / "plugin-pfx"
    try:
        create_prefix(runner, pfx)
        for src in assets:
            install_portable(runner, pfx, src, "vst3")
        found = find_installed_plugins(pfx, "vst3")
        assert {p.name for p in found} == {p.name for p in assets}, \
            "not all vst3 assets landed in the prefix"

        add_sync_targets(runner, [pfx])
        sync_yabridge(runner)
        so_files = list((pfx / "drive_c" / "Program Files" /
                         "Common Files" / "VST3").rglob("*.so"))
        assert so_files, "no bridged .so appeared after sync"
    finally:
        _cleanup(runner, pfx)

@pytest.mark.integration
def test_portable_vst2_dll_install_and_sync(runner):
    dlls = sorted(ASSETS.glob("*.dll"))
    if shutil.which("yabridgectl") is None:
        pytest.skip("yabridgectl not installed")
    if not dlls:
        pytest.skip("no .dll assets in test-assets")

    pfx = TEST_ROOT / "vst2-pfx"
    try:
        create_prefix(runner, pfx)
        install_portable(runner, pfx, dlls[0], "vst2")
        assert find_installed_plugins(pfx, "vst2"), "dll not present after install"

        add_sync_targets(runner, [pfx])
        sync_yabridge(runner)
        so_files = list((pfx / "drive_c" / "Program Files" /
                         "Steinberg" / "VstPlugins").glob("*.so"))
        assert so_files, "no bridged .so appeared after sync"
    finally:
        _cleanup(runner, pfx)
