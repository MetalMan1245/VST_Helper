# vst_helper/prefix_manager.py
"""
VST Helper — Wine prefix lifecycle management.

All operations go through Runner.prepare() so they are kind-agnostic
(stock Wine or Proton/umu). Executed synchronously here; the GUI layer
will wrap these calls in a QThread worker.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .config import ConfigError, Prefix, Runner

log = logging.getLogger(__name__)


class PrefixOperationError(ConfigError):
    """A prefix operation ran but the underlying command failed."""


def create_prefix(runner: Runner, path: Path, timeout: int = 120) -> Path:
    """Initialize a fresh Wine prefix at `path` via `wineboot -u`.

    Returns the path on success. Safe to call on an existing, healthy
    prefix (wineboot -u upgrades in place); a fresh location creates one.
    """
    if path.exists() and not (path / "drive_c").is_dir():
        raise PrefixOperationError(
            f"'{path}' exists but is not a Wine prefix — refusing to touch it"
        )

    # wineserver chdirs into the prefix at startup — it must exist first,
    # including parents (a first-ever run has no TEST_PREFIX_ROOT either)
    path.mkdir(parents=True, exist_ok=True)

    # inside create_prefix(), replacing the current subprocess.run call:
    argv, env = runner.prepare(["wineboot", "-u"], prefix=path)
    # Suppress the Mono/Gecko install prompts so first boot can't stall
    # waiting for a dialog — essential for unattended/GUI-less contexts
    env["WINEDLLOVERRIDES"] = "mscoree,mshtml="
    result = subprocess.run(argv, env=env, capture_output=True, text=True,
                            timeout=timeout)

    if not _is_initialized(path):
        raise PrefixOperationError(
            f"wineboot did not produce a valid prefix at '{path}'. "
            f"stderr: {result.stderr.strip()[:500]}"
        )
    log.info("Prefix ready at %s", path)
    return path

def _is_initialized(path: Path) -> bool:
    """A prefix is real when drive_c and the system registry exist."""
    return (path / "drive_c").is_dir() and (path / "system.reg").is_file()


def run_winetricks(runner: Runner, prefix: Path, verbs: list[str],
                   timeout: int = 600) -> None:
    """Apply winetricks verbs (e.g. ['dxvk']) inside the prefix.

    Swaps argv[0] onto winetricks but keeps the runner's env, so the
    WINEPREFIX/WINE/WINELOADER wiring from prepare() still governs it.
    """
    if shutil.which("winetricks") is None:
        raise PrefixOperationError("winetricks is not installed")

    argv, env = runner.prepare([], prefix=prefix)
    argv[0] = shutil.which("winetricks")  # type: ignore[assignment]
    result = subprocess.run([*argv, *verbs], env=env, capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode != 0:
        raise PrefixOperationError(
            f"winetricks {' '.join(verbs)} failed: {result.stderr.strip()[:500]}"
        )


def shutdown_prefix(runner: Runner, path: Path, timeout: int = 30) -> None:
    """Stop the prefix's wineserver so files can be deleted safely."""
    argv, env = runner.prepare(["wineserver", "-k"], prefix=path)
    subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)


def delete_prefix(path: Path) -> None:
    """Remove a prefix directory entirely. The shutdown step is the caller's
    responsibility (GUI flow: shutdown, then delete, then unregister)."""
    if not (path / "drive_c").is_dir():
        raise PrefixOperationError(
            f"'{path}' is not a Wine prefix — delete_prefix refuses to rm -rf blindly"
        )
    shutil.rmtree(path)
