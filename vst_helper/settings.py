# vst_helper/settings.py

from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, asdict
import tomli_w
import tomllib

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

CONFIG_DIR = Path.home() / ".config" / "vst-helper"
CONFIG_FILE = CONFIG_DIR / "vst_helper.toml"  # Match config_manager.py

@dataclass
class WineSettings:
    """Wine configuration for plugin hosting."""
    preferred_variant: str = "GE-Proton-9-21"
    custom_prefix_path: Optional[str] = None
    dxvk_enabled: bool = True
    esync_disabled: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WineSettings":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

class ConfigManager:
    """Handles TOML config persistence."""

    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.config_file = CONFIG_FILE
        self._ensure_config_exists()

    def _ensure_config_exists(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            self._create_default_config()

    def _create_default_config(self):
        default_config = {
            "plugin_dirs": [],
            "vst2_location": "centralized",
            "settings": {
                "wine_preferred_variant": "GE-Proton-9-21",
                "wine_custom_prefix": None,
                "dxvk_enabled": True,
            },
            "last_known_config": {
                "wine_version": "wine-9.21",
            }
        }
        self.save_config(default_config)

    def load_config(self) -> dict:
        with open(self.config_file, "rb") as f:
            return tomllib.load(f)

    def _filter_none(self, obj):
        """Recursively remove None values from nested dicts/lists."""
        if isinstance(obj, dict):
            return {
                k: self._filter_none(v)
                for k, v in obj.items()
                if v is not None
            }
        elif isinstance(obj, (list, tuple)):
            result = [self._filter_none(item) for item in obj if item is not None]
            return result
        else:
            return obj

    def save_config(self, config: dict):
        filtered = self._filter_none(config)
        with open(self.config_file, "wb") as f:
            tomli_w.dump(filtered, f)

    def get_wine_settings(self) -> WineSettings:
        config = self.load_config()
        wine_data = config.get("settings", {}).get("wine", {})
        return WineSettings.from_dict({
            "preferred_variant": config.get("settings", {}).get("wine_preferred_variant", "GE-Proton-9-21"),
            "custom_prefix_path": config.get("settings", {}).get("wine_custom_prefix"),
            "dxvk_enabled": config.get("settings", {}).get("dxvk_enabled", True),
            "esync_disabled": config.get("settings", {}).get("esync_disabled", False),
        })

    def update_wine_settings(self, settings: WineSettings):
        config = self.load_config()
        config.setdefault("settings", {})
        config["settings"]["wine_preferred_variant"] = settings.preferred_variant
        config["settings"]["wine_custom_prefix"] = settings.custom_prefix_path
        config["settings"]["dxvk_enabled"] = settings.dxvk_enabled
        config["settings"]["esync_disabled"] = settings.esync_disabled
        self.save_config(config)

class SettingsDialog(QDialog):
    refresh_triggered = pyqtSignal()

    def __init__(self, parent=None, wine_manager=None):
        super().__init__(parent)
        self.wine_manager = wine_manager
        self.setWindowTitle("VST Helper — Settings")
        self.setMinimumWidth(480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Wine Configuration</b>"))

        self.wine_status = QLabel("Wine: …")
        self.wine_status.setWordWrap(True)
        layout.addWidget(self.wine_status)

        btn_row = QHBoxLayout()
        manage_btn = QPushButton("Manage Wine Versions…")
        manage_btn.clicked.connect(self._manage_wine)
        btn_row.addWidget(manage_btn)

        reaper_btn = QPushButton("Apply to REAPER .desktop")
        reaper_btn.clicked.connect(self._apply_to_reaper)
        btn_row.addWidget(reaper_btn)
        layout.addLayout(btn_row)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._refresh_wine_status()

    def _refresh_wine_status(self):
        if self.wine_manager is None:
            self.wine_status.setText("Wine management unavailable (no wine manager).")
            return
        try:
            from .wine_manager import is_variant_installed, wine_binary_path
            variant = self.wine_manager.get_current_variant()
            installed = is_variant_installed(variant)
            path = wine_binary_path(variant)
            state = "installed" if installed else "NOT installed"
            self.wine_status.setText(
                f"Active variant: {variant} ({state})\nBinary: {path}"
            )
        except Exception as e:
            self.wine_status.setText(f"Could not read Wine settings: {e}")

    def _manage_wine(self):
        if self.wine_manager is None:
            return
        # Deferred import: gui_main imports this module at load time
        from .gui_main import WineVariantDialog
        dialog = WineVariantDialog(self, self.wine_manager)
        dialog.exec()
        self._refresh_wine_status()
        self.refresh_triggered.emit()

    def _apply_to_reaper(self):
        if self.wine_manager is None:
            return
        from .reaper_config import apply_active_variant_to_reaper
        ok, msg = apply_active_variant_to_reaper(self.wine_manager)
        if ok:
            QMessageBox.information(self, "REAPER Updated", f"Updated: {msg}")
        else:
            QMessageBox.warning(self, "REAPER Update Failed", msg)
