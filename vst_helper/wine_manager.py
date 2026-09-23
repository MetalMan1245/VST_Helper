"""App-managed portable Wine builds for VST Helper.

Pins a known-good Wine version (9.21 for yabridge compatibility)
under ~/.local/share/vst-helper/runners/, independent of system Wine.
"""

import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import HTTPError

RUNNERS_ROOT = Path.home() / ".local" / "share" / "vst-helper" / "runners"
PINNED_VERSION = "9.21"

# Try these artifact names in order; adjust based on what's actually on the
# Kron4ek release page: https://github.com/Kron4ek/Wine-Builds/releases

ARTIFACT_NAMES = [
    f"wine-{PINNED_VERSION}-staging-tkg-amd64.tar.xz",
    f"wine-{PINNED_VERSION}-staging-amd64.tar.xz",
    f"wine-{PINNED_VERSION}-staging-tkg-x86.tar.xz",
]

BASE_URL = (
    "https://github.com/Kron4ek/Wine-Builds/releases/download/"
    f"{PINNED_VERSION}/"
)

def pinned_wine_binary(version: str = PINNED_VERSION) -> Path:
    """Path of the wine binary inside the app-managed build."""
    return RUNNERS_ROOT / f"wine-{version}" / "bin" / "wine"

def is_pinned_installed(version: str = PINNED_VERSION) -> bool:
    return pinned_wine_binary(version).is_file()

def install_pinned(version: str = PINNED_VERSION, progress=print) -> Path:
    """Download and extract a portable Wine build. Returns wine binary path."""
    if is_pinned_installed(version):
        progress(f" Wine {version} already installed")
        return pinned_wine_binary(version)

    RUNNERS_ROOT.mkdir(parents=True, exist_ok=True)

    downloaded_archive = None
    used_artifact = None
    tmpdir = None

    for artifact in ARTIFACT_NAMES:
        url = BASE_URL + artifact
        progress(f"Attempting {artifact}...")

        archive = Path("/tmp") / f"vst-helper-{artifact}"
        try:
            urlretrieve(url, archive)
            progress(f"  Downloaded ({archive.stat().st_size // (1024*1024)}MB)")
            downloaded_archive = archive
            used_artifact = artifact
            break
        except Exception as e:
            progress(f"  Failed: {e}")
            continue

    if downloaded_archive is None:
        raise FileNotFoundError(
            f"All variants failed. Check the release assets at:\n"
            f"https://github.com/Kron4ek/Wine-Builds/releases/tag/{PINNED_VERSION}\n"
            f"and update ARTIFACT_NAMES in wine_manager.py to match."
        )

    try:
        with tarfile.open(str(downloaded_archive), "r:xz") as tar:
            members = tar.getmembers()
            dirs = [m.name for m in members if m.isdir()]
            if dirs:
                source_dir = min(dirs, key=len)
                tar.extractall(RUNNERS_ROOT)
                extracted = RUNNERS_ROOT / source_dir
                if extracted.exists():
                    extracted.rename(RUNNERS_ROOT / f"wine-{version}")
            else:
                tar.extractall(RUNNERS_ROOT)
    finally:
        downloaded_archive.unlink(missing_ok=True)

    binary = pinned_wine_binary(version)
    if not binary.is_file():
        raise FileNotFoundError(
            f"Archive extracted but {binary} not found. "
            f"Extracted: {used_artifact}"
        )

    binary.chmod(binary.stat().st_mode | 0o111)
    progress(f"Wine {version} installed at {binary}")
    return binary
