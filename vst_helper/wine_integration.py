# vst_helper/wine_integration.py

from pathlib import Path
from .wine_manager import (
    install_variant,
    is_variant_installed,
    wine_binary_path,
    available_variants,
    list_installed,
    DEFAULT_VARIANT,
)
from .settings import ConfigManager, WineSettings

class WineManager:
    """Integration layer between wine_manager and app settings."""

    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager

    def get_active_wine_binary(self) -> Path:
        """Get the currently configured Wine binary path."""
        wine_settings = self.config.get_wine_settings()
        variant = wine_settings.preferred_variant

        if not is_variant_installed(variant):
            # Auto-install if missing
            self.install_variant(variant)

        return wine_binary_path(variant)

    def get_current_variant(self) -> str:
        """Return the variant name currently selected in settings."""
        return self.config.get_wine_settings().preferred_variant

    def get_active_wine_binary(self) -> Path:
        """Resolve the configured variant's binary, installing if missing.

        Does not change the stored preference.
        """
        variant = self.get_current_variant()
        if not is_variant_installed(variant):
            install_variant(variant)
        return wine_binary_path(variant)

    def install_variant(self, variant_name: str) -> Path:
        """Install a variant WITHOUT changing the active preference."""
        if variant_name not in available_variants():
            raise ValueError(
                f"Unknown variant: {variant_name}. Available: {available_variants()}"
            )
        return install_variant(variant_name)

    def switch_variant(self, variant_name: str) -> Path:
        """Install if needed, make active, and persist the preference."""
        if variant_name not in available_variants():
            raise ValueError(
                f"Unknown variant: {variant_name}. Available: {available_variants()}"
            )
        wine_bin = install_variant(variant_name)
        wine_settings = self.config.get_wine_settings()
        wine_settings.preferred_variant = variant_name
        self.config.update_wine_settings(wine_settings)
        return wine_bin

    def get_active_prefix_path(self) -> Path:
        """Get the Wine prefix path (default or custom)."""
        wine_settings = self.config.get_wine_settings()

        if wine_settings.custom_prefix_path:
            return Path(wine_settings.custom_prefix_path)

        # Default prefix location
        return Path.home() / ".local" / "share" / "vst-helper" / "prefixes" / "default"

    def create_env_vars_for_yabridge(self) -> dict:
        """Return environment variables for yabridge to use correct Wine."""
        wine_binary = self.get_active_wine_binary()
        prefix_path = self.get_active_prefix_path()

        return {
            "WINELOADER": str(wine_binary),
            "WINEPREFIX": str(prefix_path),
        }
