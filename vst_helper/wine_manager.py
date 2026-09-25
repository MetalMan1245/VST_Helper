"""App-managed portable Wine/Proton builds for VST Helper.

Supports multiple Wine variants (GE-Proton, Wine-TKG, etc.) with
pinned known-good versions for yabridge compatibility and DAW licensing fixes.
"""

import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import HTTPError
from typing import Dict, List, Optional, NamedTuple

RUNNERS_ROOT = Path.home() / ".local" / "share" / "vst-helper" / "runners"


class WineVariant(NamedTuple):
    """Defines a downloadable Wine/Proton variant."""
    name: str                          # Internal identifier (e.g., "GE-Proton-9-21")
    version: str                       # Display version (e.g., "9.21")
    variant_type: str                  # "ge-proton", "wine-tkg", "wine-stable"
    base_url: str                      # Release URL (without trailing filename)
    artifact_name: str                 # Archive filename
    extract_dir_pattern: str           # Pattern to find root dir in archive
    wine_binary_path: str              # Relative path to wine binary inside archive


# =============================================================================
# PINNED VERSIONS CONFIGURATION
# Add new variants here - they will automatically be available for installation
# =============================================================================

PINNED_VARIANTS: Dict[str, WineVariant] = {
    "GE-Proton-9-21": WineVariant(
        name="GE-Proton-9-21",
        version="9.21",
        variant_type="ge-proton",
        base_url=(
            "https://github.com/GloriousEggroll/proton-ge-custom/releases/download/"
            "GE-Proton9-21"
        ),
        artifact_name="GE-Proton9-21.tar.gz",
        extract_dir_pattern="GE-Proton9-21",
        wine_binary_path="files/bin/wine",
    ),
    "Wine-TKG-9-21": WineVariant(
        name="Wine-TKG-9-21",
        version="9.21",
        variant_type="wine-tkg",
        base_url=(
            "https://github.com/Kron4ek/Wine-Builds/releases/download/9.21"
        ),
        artifact_name="wine-9.21-staging-tkg-amd64.tar.xz",
        extract_dir_pattern="wine-9.21",
        wine_binary_path="bin/wine",
    ),
    # Future additions go here - example:
    # "GE-Proton-9-27": WineVariant(
    #     name="GE-Proton-9-27",
    #     version="9.27",
    #     variant_type="ge-proton",
    #     base_url="https://...",
    #     artifact_name="GE-Proton9-27.tar.gz",
    #     extract_dir_pattern="GE-Proton9-27",
    #     wine_binary_path="files/bin/wine",
    # ),
}

DEFAULT_VARIANT = "GE-Proton-9-21"  # What gets installed if no variant specified


def get_variant(variant_name: str) -> WineVariant:
    """Get variant definition by name."""
    if variant_name not in PINNED_VARIANTS:
        raise ValueError(
            f"Unknown variant '{variant_name}'. "
            f"Available: {', '.join(PINNED_VARIANTS.keys())}"
        )
    return PINNED_VARIANTS[variant_name]


def available_variants() -> List[str]:
    """List all available pinned variant names."""
    return list(PINNED_VARIANTS.keys())


def wine_binary_path(variant_name: str) -> Path:
    """Get the full path to the wine binary for a variant."""
    variant = get_variant(variant_name)
    return RUNNERS_ROOT / variant.name / variant.wine_binary_path


def is_variant_installed(variant_name: str) -> bool:
    """Check if a specific variant is installed."""
    return wine_binary_path(variant_name).is_file()


def is_default_installed() -> bool:
    """Check if the default variant is installed."""
    return is_variant_installed(DEFAULT_VARIANT)


def _find_extracted_root(tar: tarfile.TarFile, pattern: str) -> Optional[str]:
    """Find the root directory pattern in a tar archive."""
    members = tar.getmembers()

    # Look for exact match first
    for member in members:
        if member.isdir() and member.name == pattern:
            return member.name

    # Look for prefix match (handles variations like "GE-Proton9-21-xxxx")
    for member in members:
        if member.isdir() and member.name.startswith(pattern.split("-")[0]):
            return member.name

    # Return shortest directory as fallback
    dirs = [m.name for m in members if m.isdir()]
    return min(dirs, key=len) if dirs else None


def install_variant(
    variant_name: str,
    progress=print
) -> Path:
    """
    Download and extract a Wine/Proton variant.

    Args:
        variant_name: Key from PINNED_VARIANTS dict
        progress: Callback for progress messages (default: print)

    Returns:
        Path to the wine binary

    Raises:
        ValueError: If variant_name not in PINNED_VARIANTS
        FileNotFoundError: If download or extraction fails
    """
    variant = get_variant(variant_name)
    wine_bin = wine_binary_path(variant_name)

    if wine_bin.is_file():
        progress(f"  {variant_name} already installed")
        return wine_bin

    RUNNERS_ROOT.mkdir(parents=True, exist_ok=True)
    progress(f"Installing {variant_name}...")

    archive = Path("/tmp") / f"vst-helper-{variant.artifact_name}"

    try:
        # Download
        progress(f"  Downloading {variant.artifact_name}...")
        urlretrieve(variant.base_url + "/" + variant.artifact_name, archive)
        progress(f"  Downloaded ({archive.stat().st_size // (1024*1024)} MB)")

        # Extract
        progress("  Extracting...")
        with tarfile.open(str(archive), "r:*") as tar:
            extract_root = _find_extracted_root(tar, variant.extract_dir_pattern)

            if extract_root is None:
                raise RuntimeError(
                    f"Could not find directory matching '{variant.extract_dir_pattern}' "
                    f"in archive. Available directories: {[m.name for m in tar.getmembers() if m.isdir()]}"
                )

            # Extract to temp location first
            with tempfile.TemporaryDirectory() as tmpdir:
                tar.extractall(tmpdir)

                extracted_source = Path(tmpdir) / extract_root

                # Rename to variant name
                target = RUNNERS_ROOT / variant.name
                if extracted_source.exists():
                    shutil.move(str(extracted_source), str(target))

        # Make wine executable
        if wine_bin.is_file():
            wine_bin.chmod(wine_bin.stat().st_mode | 0o111)
            progress(f"  {variant_name} installed at {wine_bin}")
            return wine_bin
        else:
            raise FileNotFoundError(
                f"Extraction complete but wine binary not found at {wine_bin}. "
                f"Expected path pattern: {variant.wine_binary_path}"
            )

    except HTTPError as e:
        raise FileNotFoundError(
            f"Failed to download {variant.artifact_name}: HTTP {e.code}\n"
            f"Check: {variant.base_url}/{variant.artifact_name}"
        )
    except Exception as e:
        raise FileNotFoundError(f"Installation failed: {e}")
    finally:
        archive.unlink(missing_ok=True)


def install_default(progress=print) -> Path:
    """Install the default variant (GE-Proton 9.21)."""
    return install_variant(DEFAULT_VARIANT, progress)


def uninstall_variant(variant_name: str, progress=print) -> bool:
    """Remove a specific variant."""
    if variant_name not in PINNED_VARIANTS:
        raise ValueError(f"Unknown variant: {variant_name}")

    variant = get_variant(variant_name)
    variant_dir = RUNNERS_ROOT / variant.name

    if not variant_dir.exists():
        progress(f"  {variant_name} not installed")
        return False

    shutil.rmtree(variant_dir)
    progress(f"  Uninstalled {variant_name}")
    return True


def list_installed() -> List[str]:
    """List all currently installed variants."""
    return [
        name for name in PINNED_VARIANTS.keys()
        if is_variant_installed(name)
    ]


def ensure_default_installed(progress=print) -> Path:
    """
    Ensure the default variant is installed, installing if necessary.

    Returns:
        Path to the wine binary
    """
    if not is_default_installed():
        progress(f"{DEFAULT_VARIANT} not installed. Installing...")
        return install_default(progress)

    progress(f"{DEFAULT_VARIANT} already installed")
    return wine_binary_path(DEFAULT_VARIANT)


# =============================================================================
# CLI INTERFACE (for testing/direct use)
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage Wine/Proton variants")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Install command
    install_parser = subparsers.add_parser("install", help="Install a variant")
    install_parser.add_argument(
        "variant", nargs="?", default=DEFAULT_VARIANT,
        help=f"Variant name (default: {DEFAULT_VARIANT})"
    )

    # Uninstall command
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall a variant")
    uninstall_parser.add_argument("variant", help="Variant name to remove")

    # List command
    subparsers.add_parser("list", help="List installed variants")

    # List-available command
    subparsers.add_parser("available", help="List all available variants")

    args = parser.parse_args()

    if args.command == "install":
        install_variant(args.variant)
    elif args.command == "uninstall":
        uninstall_variant(args.variant)
    elif args.command == "list":
        installed = list_installed()
        print("Installed variants:")
        for v in installed:
            marker = "(default)" if v == DEFAULT_VARIANT else ""
            print(f"  {v} {marker}")
        if not installed:
            print("  (none)")
    elif args.command == "available":
        print("Available variants:")
        for name, var in PINNED_VARIANTS.items():
            marker = "(default)" if name == DEFAULT_VARIANT else ""
            print(f"  {name} v{var.version} ({var.variant_type}) {marker}")
    else:
        parser.print_help()
