# vst_helper/plugin_installer.py
"""
VST Helper — plugin installation and yabridgectl integration.

Two install paths:
  - installer-backed (.exe): launched in the prefix, interactive, we wait
  - portable (raw .vst3/.clap): copied directly into the prefix's VST dirs

All Wine execution goes through Runner.prepare() — kind-agnostic.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import Plugin, Prefix, Runner
from .prefix_manager import PrefixOperationError

log = logging.getLogger(__name__)

class InstallError(PrefixOperationError):
    """Plugin installation failed."""

# Windows-side canonical plugin directories inside drive_c
FORMAT_DIRS = {
    "vst3": "Program Files/Common Files/VST3",
    "vst2": "Program Files/Steinberg/VstPlugins",
    "clap": "Program Files/Common Files/CLAP",
}

def _run_captured(argv: list[str], env: dict[str, str],
                  timeout: int) -> subprocess.CompletedProcess:
    """Run a command capturing output WITHOUT pipes.

    yabridgectl (and Wine commands generally) may daemonize wineserver,
    which inherits the captured fds and keeps the pipe write-ends open
    forever — communicate() then blocks even after the main process exits.
    Writing to a temp file instead: a lingering child holding the fd open
    is harmless because nobody waits for EOF on a file.
    """
    with tempfile.TemporaryFile(mode="w+") as out, \
         tempfile.TemporaryFile(mode="w+") as err:
        proc = subprocess.run(argv, env=env, stdout=out, stderr=err,
                              timeout=timeout)
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(
            argv, proc.returncode, stdout=out.read(), stderr=err.read()
        )

def install_portable(runner: Runner, prefix_path: Path, source: Path,
                      fmt: str) -> Path:
    """Copy a raw plugin file/bundle into the prefix's format directory.

    The destination inside drive_c IS the prefix/plugin association —
    there is no separate registry of mappings to get out of sync.
    Returns the destination path inside the prefix.
    """
    if fmt not in FORMAT_DIRS:
        raise InstallError(f"Unknown plugin format '{fmt}' for portable install")

    if not source.exists():
        raise InstallError(f"Source plugin not found: {source}")

    dest_dir = prefix_path / "drive_c" / FORMAT_DIRS[fmt]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name

    if dest.exists():
        log.info("Overwriting existing plugin at %s", dest)
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()

    if source.is_dir():  # .vst3 bundles are directories
        shutil.copytree(source, dest)
    else:
        shutil.copy2(source, dest)

    log.info("Installed portable plugin: %s -> %s", source, dest)
    return dest

def install_from_installer(runner: Runner, prefix_path: Path,
                           installer: Path) -> int:
    """Run a plugin installer .exe inside the prefix. Interactive by
    nature: the user drives the installer GUI; we wait for completion.

    STDOUT/STDERR are inherited (not captured) so Wine/installer messages
    appear wherever VST Helper's console output goes. Returns the
    installer's exit code — 0 does NOT imply a plugin was installed, only
    that the installer exited cleanly.
    """
    if not installer.is_file():
        raise InstallError(f"Installer not found: {installer}")

    argv, env = runner.prepare([str(installer)], prefix=prefix_path)
    log.info("Launching installer in %s: %s", prefix_path, installer.name)
    # No timeout: user-paced GUI. No capture: must remain visible.
    result = subprocess.run(argv, env=env)
    if result.returncode != 0:
        log.warning("Installer exited with code %d", result.returncode)
    return result.returncode

def find_installed_plugins(prefix_path: Path, fmt: str) -> list[Path]:
    """Enumerate plugins of `fmt` inside a prefix — used to detect what an
    installer actually dropped, and as the input list for sync."""
    if fmt not in FORMAT_DIRS:
        raise InstallError(f"Unknown plugin format '{fmt}'")
    fmt_dir = prefix_path / "drive_c" / FORMAT_DIRS[fmt]
    if not fmt_dir.is_dir():
        return []
    pattern = "*.vst3" if fmt == "vst3" else "*.clap" if fmt == "clap" else "*.dll"
    return sorted(fmt_dir.glob(pattern))

def add_sync_targets(runner: Runner, paths: list[Path],
                     timeout: int = 120) -> None:
    """Register plugin directories with yabridgectl (`yabridgectl add <path>`
    — positional path; the --path= form was removed in newer releases).

    Idempotent — re-adding a known directory is a no-op in yabridgectl,
    so this is safe to call on every sync flow.
    """
    if shutil.which("yabridgectl") is None:
        raise InstallError("yabridgectl is not installed")

    argv, env = runner.prepare([], prefix=None)  # env only: loader + PATH
    argv[0] = shutil.which("yabridgectl")        # type: ignore[assignment]
    # Expand prefix roots to their canonical plugin directories — handing
    # yabridgectl a whole prefix makes sync index drive_c recursively
    # (100k+ files). Adopted prefixes pass their plugin dirs directly.
    dirs: set[Path] = set()
    for path in paths:
        if (path / "drive_c").is_dir():
            base = path / "drive_c"
            # Pre-create every format directory even when empty: the
            # user may install into it later, and since the path is
            # already registered, a subsequent bare `sync` picks it up.
            for d in FORMAT_DIRS.values():
                (base / d).mkdir(parents=True, exist_ok=True)
            dirs.update(base / d for d in FORMAT_DIRS.values())
        else:
            dirs.add(path)
    for path in sorted(dirs):
        result = _run_captured([*argv, "add", str(path)], env, timeout)
        if result.returncode != 0:
            raise InstallError(
                f"yabridgectl add {path} failed: "
                f"{result.stderr.strip()[:500]}"
            )

def sync_yabridge(runner: Runner, timeout: int = 600) -> None:
    """Run bare `yabridgectl sync` — it processes every registered path.

    Runs under the runner's environment (WINELOADER + PATH pair) so bridged
    plugins host under the SAME Wine version that will later run them from
    the DAW. This pairing is load-bearing: a sync performed with system
    Wine followed by DAW launches via a pinned runner reproduces the
    version-mismatch bug we originally debugged.

    Output capture uses _run_captured (temp files, not pipes): sync spawns
    wineserver, which daemonizes and would otherwise hold the pipe open
    and wedge us in communicate() indefinitely.
    """
    if shutil.which("yabridgectl") is None:
        raise InstallError("yabridgectl is not installed")

    argv, env = runner.prepare([], prefix=None)
    argv[0] = shutil.which("yabridgectl")        # type: ignore[assignment]
    result = _run_captured([*argv, "sync"], env, timeout)
    if result.returncode != 0:
        raise InstallError(
            f"yabridgectl sync failed: {result.stderr.strip()[:500]}"
        )
    log.info("yabridgectl sync output: %s", result.stdout.strip()[:500])
