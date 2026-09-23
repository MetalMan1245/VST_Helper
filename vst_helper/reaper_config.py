"""Minimal REAPER .desktop modification for Wine override."""

from pathlib import Path

def get_reaper_desktop_path() -> Path | None:
    """Find REAPER's .desktop file with expanded search."""
    import glob as stdlib_glob

    # Common names that might exist
    common_names = [
        "reaper.desktop",
        "REAPER.desktop",
        "cockos-reaper.desktop",
        "Cockos_REAPER.desktop",
        "reaper64.desktop",
        "REAPER64.desktop",
    ]

    # Standard locations to search
    search_paths = [
        Path("/usr/share/applications"),
        Path.home() / ".local" / "share" / "applications",
        Path("/usr/local/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        Path.home() / ".local" / "share" / "flatpak" / "exports" / "applications",
    ]

    # Search each location for common names
    for search_path in search_paths:
        if not search_path.exists():
            continue

        for name in common_names:
            candidate = search_path / name
            if candidate.exists():
                return candidate

        # Also search for any desktop file containing "reaper" (case-insensitive)
        try:
            matches = stdlib_glob.glob(str(search_path / "*[rR][eE][aA][pP][eE][rR]*.desktop"))
            for match in matches:
                path = Path(match)
                if path.exists():
                    return path
        except Exception:
            pass

    return None

def pick_reaper_desktop_fallback() -> Path | None:
    """Interactive file picker for REAPER .desktop file."""
    # Import only when called to avoid circular deps
    from PyQt6.QtWidgets import QFileDialog, QApplication
    from pathlib import Path

    start_dir = Path.home() / ".local" / "share" / "applications"
    if not start_dir.exists():
        start_dir = Path("/usr/share/applications")

    path, _ = QFileDialog.getOpenFileName(
        None,
        "Select REAPER .desktop file",
        str(start_dir),
        "Desktop Files (*.desktop);;All Files (*)"
    )

    if not path:
        return None

    return Path(path)

def modify_reaper_exec_with_wine(wine_path: Path) -> tuple[bool, str]:
    """Modify REAPER's .desktop Exec line via pkexec for system locations."""
    reaper_desktop = get_reaper_desktop_path()

    if not reaper_desktop:
        return False, "Could not find REAPER .desktop file"

    original = reaper_desktop.read_text()
    lines = []

    for line in original.splitlines():
        if line.startswith("Exec="):
            rest = line.split("=", 1)[1]
            lines.append(f'Exec=env WINELOADER={wine_path} {rest}')
        else:
            lines.append(line)

    new_content = "\n".join(lines) + "\n"

    # If writable by user, do it directly
    import os
    stat_info = reaper_desktop.stat()
    current_uid = os.getuid()

    if stat_info.st_uid == current_uid or os.access(reaper_desktop, os.W_OK):
        try:
            reaper_desktop.write_text(new_content)
            return True, str(reaper_desktop)
        except PermissionError:
            pass  # Fall through to pkexec

    # Need sudo elevation via pkexec
    command = f"echo '{new_content.replace(chr(39), chr(39))}' > {reaper_desktop}"

    from subprocess import run
    result = run(
        ["pkexec", "sh", "-c", f"cat > {reaper_desktop} << 'EOFD'\n{new_content}EOFD\n"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        return False, f"Permission denied: {result.stderr}"

    return True, str(reaper_desktop)
