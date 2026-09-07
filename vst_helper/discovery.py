# vst_helper/discovery.py
"""
VST Helper — Wine runner discovery.

Scans known locations (Heroic's tools directory, Steam's compatibilitytools.d,
system PATH) for Wine binaries, verifies each one actually runs, and returns
them as Runner records ready for the registry.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from .config import Runner

log = logging.getLogger(__name__)

# Heroic exposes Wine via LinuxGameResolver/WineManager under these roots
HEROIC_ROOTS = [
    "~/.config/heroic/tools/wine",
]

STEAM_PROTON_ROOTS = [
    "~/.steam/steam/compatibilitytools.d",
    "~/.local/share/Steam/compatibilitytools.d",
]


def _candidate_wine_dirs(root: Path) -> list[Path]:
    """One level below a tools root: each subdir is one runner."""
    if not root.is_dir():
        return []
    return [
        d for d in sorted(root.iterdir())
        if d.is_dir() and (d / "bin" / "wine").is_file()
    ]


def discover(search_roots: list[Path]) -> list[Runner]:
    """Find verified wine binaries under the given roots. Roots may contain
    subdirectories shaped like <wine-tool>/<...>/bin/wine (Heroic, Steam tools)
    — each is probed and only working binaries are returned."""
    found: dict[str, Runner] = {}

    for root in search_roots:
        expanded = root.expanduser()
        if not expanded.is_dir():
            continue
        for wine_bin in sorted(expanded.glob("**/bin/wine")):
            candidate = Runner(
                name=_derive_name(wine_bin),
                path=wine_bin,
            )
            try:
                version = candidate.verify()
            except Exception as exc:
                # Non-executable or broken wine — skip, don't fail the scan
                log.warning("Skipping %s: %s", candidate.path, candidate.name, exc_info=exc)
                continue
            found.setdefault(candidate.name, candidate)
            log.debug("Found runner %s: %s", candidate.name, version)

    return list(found.values())


def _derive_name(wine_path: Path) -> str:
    """Human-readable name from the path: .../wine-9.21-staging-amd64/bin/wine
    -> heroic-wine-9.21-staging if the parent chain is recognizable, else the
    runner directory name. Callers dedupe collisions."""
    parts = wine_path.parts
    if len(parts) >= 3:
        # .../<runner-name>/bin/wine — take the immediate runner directory
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else "wine"


def discover_all() -> list[Runner]:
    """Scan all well-known locations, plus whatever `wine` is on PATH."""
    roots = [Path(p) for p in HEROIC_ROOTS + STEAM_PROTON_ROOTS]
    runners = discover(roots)

    system_wine = shutil.which("wine")  # move to a top-level import
    if system_wine:
        candidate = Runner(name="system", path=Path(system_wine))
        try:
            candidate.verify()
        except Exception as e:
            log.warning("System wine failed probe: %s", e)
        else:
            if all(r.path.resolve() != candidate.path.resolve() for r in runners):
                runners.append(candidate)

    return runners
