# scripts/manual_installer_test.py — run with: .venv/bin/python scripts/manual_installer_test.py
from pathlib import Path

from vst_helper.config import Runner
from vst_helper.prefix_manager import create_prefix, shutdown_prefix
from vst_helper.plugin_installer import (
    find_installed_plugins, install_from_installer,
    add_sync_targets, sync_yabridge,
)

assets = Path("/home/f/Dev/VST_Helper/test-assets")
exe = next(assets.glob("*.exe"))
pfx = Path("~/.local/share/vst-helper-test/installer-pfx").expanduser()

runner = Runner(name="manual", path=next(iter(sorted(Path(
    "~/.config/heroic/tools/wine").expanduser().glob("*/bin/wine")))))

print("Before:", [p.name for p in find_installed_plugins(pfx, "vst3")]
      if pfx.exists() else "(no prefix)")
create_prefix(runner, pfx)
install_from_installer(runner, pfx, exe)   # you click through the GUI
print("After:", [p.name for p in find_installed_plugins(pfx, "vst3")])
add_sync_targets(runner, [pfx])
sync_yabridge(runner)
shutdown_prefix(runner, pfx)
