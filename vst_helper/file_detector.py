"""File type detection for VST Helper."""

import os
import subprocess
from pathlib import Path
from enum import Enum
from typing import Optional


class FileType(Enum):
    """Supported plugin file types."""
    LINUX_VST3 = "linux_vst3"
    LINUX_CLAP = "linux_clap"
    LINUX_LV2 = "linux_lv2"
    WINDOWS_EXE = "windows_exe"
    WINDOWS_VST3 = "windows_vst3"
    WINDOWS_CLAP = "windows_clap"
    WINDOWS_DLL = "windows_dll"
    WINDOWS_RAW = "windows_raw"
    UNKNOWN = "unknown"


def detect_file_type(file_path: Path) -> FileType:
    """Detect whether a file is Linux or Windows binary and its plugin type."""

    if not file_path.exists():
        return FileType.UNKNOWN

    ext = file_path.suffix.lower()

    # Check extension first for common cases
    if ext == ".vst3":
        # Need to check if it's Linux (.so inside bundle) or Windows (raw vst3)
        if file_path.is_dir():
            # Linux VST3 is a bundle with Contents/x86_64-linux/*.so
            if (file_path / "Contents" / "x86_64-linux").exists():
                return FileType.LINUX_VST3
            return FileType.WINDOWS_VST3
        else:
            # Single-file vst3 (Windows)
            return FileType.WINDOWS_VST3

    elif ext == ".clap":
        if file_path.is_dir():
            return FileType.LINUX_CLAP
        else:
            return FileType.WINDOWS_CLAP  # fallback, treat as Windows

    elif ext == ".lv2":
        # LV2 is always a directory bundle
        if file_path.is_dir() and (file_path / "manifest.ttl").exists():
            return FileType.LINUX_LV2
        return FileType.UNKNOWN

    elif ext == ".exe":
        return FileType.WINDOWS_EXE

    elif ext == ".dll":
        return FileType.WINDOWS_DLL

    # For files without extensions, use file command
    try:
        result = subprocess.run(
            ["file", "--mime-type", str(file_path)],
            capture_output=True,
            text=True,
            timeout=5
        )

        mime = result.stdout.split(":")[-1].strip() if result.returncode == 0 else ""

        if "x-dll" in mime or "x-ms-windows" in mime:
            return FileType.WINDOWS_DLL

        # Check for PE signature manually
        with open(file_path, "rb") as f:
            header = f.read(2)
            if header == b"MZ":  # DOS/PE signature
                return FileType.WINDOWS_RAW

    except (subprocess.TimeoutExpired, FileNotFoundError, IOError):
        pass

    return FileType.UNKNOWN


def is_linux_binary(file_path: Path) -> bool:
    """Quick check if file is a Linux ELF binary."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(4)
            return header[:4] == b"\x7fELF"
    except (IOError, OSError):
        return False


def is_windows_binary(file_path: Path) -> bool:
    """Quick check if file is a Windows PE binary."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(2)
            return header == b"MZ"
    except (IOError, OSError):
        return False
