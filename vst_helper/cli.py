"""CLI entry point for VST Helper."""

import sys
import argparse
from pathlib import Path
from typing import Optional

from .file_detector import detect_file_type, FileType
from .health_check import run_full_health_check


def handle_file(path: Path) -> None:
    """Handle processing of a single file/directory."""
    from .health_check import check_wine

    file_type = detect_file_type(path)

    if file_type == FileType.UNKNOWN:
        print(f"Error: Cannot determine type of {path}")
        sys.exit(1)

    # Determine if Wine is required
    is_windows = file_type in (
        FileType.WINDOWS_EXE,
        FileType.WINDOWS_VST3,
        FileType.WINDOWS_DLL,
        FileType.WINDOWS_RAW
    )

    if is_windows:
        wine_status = check_wine(required_for_operation=True)
        if wine_status.status.value == "error":
            print(f"Error: Windows plugin detected ({path}), but Wine is required.")
            print(wine_status.message)
            sys.exit(1)

    # Run full health check
    results = run_full_health_check(for_windows_plugin=is_windows)

    warnings = [r for r in results if r.status.value in ("warning", "error")]
    for warning in warnings:
        print(f"[Warning] {warning.component}: {warning.message}")

    # TODO: Actually process the file (this is where GUI integration happens)
    print(f"Detected: {file_type.value} at {path}")
    print("Ready to process. Use the GUI or configure further via CLI options.")


def main(args: Optional[list] = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="vst-helper",
        description="Easy way to run Windows VST plugins on Linux"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # 'open' command - open GUI or process file
    open_parser = subparsers.add_parser("open", help="Open GUI or process file")
    open_parser.add_argument(
        "file_or_dir",
        nargs="?",
        type=Path,
        help="Plugin file or directory to process"
    )
    open_parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Skip GUI, process file directly if possible"
    )

    # 'health' command - just run health check
    health_parser = subparsers.add_parser("health", help="Run health check only")
    health_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )

    parsed = parser.parse_args(args)

    if parsed.command == "health":
        results = run_full_health_check()
        for r in results:
            status_marker = {
                "ok": "✓",
                "warning": "⚠",
                "error": "✗",
                "skipped": "○"
            }.get(r.status.value, "?")

            print(f"{status_marker} {r.component}: {r.message}")

        has_errors = any(r.status.value == "error" for r in results)
        return 1 if has_errors else 0

    elif parsed.command == "open":
        if parsed.file_or_dir:
            handle_file(parsed.file_or_dir)
        elif not parsed.no_gui:
            # Launch GUI
            from .gui_main import main as gui_main
            return gui_main()
        else:
            parser.print_help()
            return 1

    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
