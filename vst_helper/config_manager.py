"""Configuration manager for VST Helper - tracks plugins and prefixes."""

import tomllib
import tomli_w
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "vst-helper"
CONFIG_FILE = CONFIG_DIR / "vst_helper.toml"

def ensure_config_dir():
    """Ensure config directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def load_config() -> dict[str, Any]:
    """Load config from file, return empty config if not found."""
    ensure_config_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    return {"prefixes": [], "plugins": []}

def save_config(config: dict[str, Any]):
    """Save config to file."""
    ensure_config_dir()
    print(f"DEBUG: Saving config to {CONFIG_FILE}")
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(config, f)
    print(f"DEBUG: Config file exists: {CONFIG_FILE.exists()}")

def register_prefix(prefix_path: str, runner_name: str, dxvk_installed: bool = False) -> None:
    """Register a Wine prefix."""
    config = load_config()

    existing = [p for p in config["prefixes"] if p["path"] == prefix_path]
    if not existing:
        config["prefixes"].append({
            "path": prefix_path,
            "runner": runner_name,
            "dxvk_installed": dxvk_installed
        })
        save_config(config)

def unregister_prefix(prefix_path: str) -> None:
    """Unregister a Wine prefix."""
    config = load_config()
    config["prefixes"] = [p for p in config["prefixes"] if p["path"] != prefix_path]
    save_config(config)

def register_plugin(prefix_path: str, plugin_name: str, plugin_type: str, kind: str) -> None:
    """Register an installed plugin."""
    config = load_config()

    existing = [p for p in config["plugins"]
                if p["prefix"] == prefix_path and p["name"] == plugin_name]
    if not existing:
        config["plugins"].append({
            "prefix": prefix_path,
            "name": plugin_name,
            "type": plugin_type,
            "kind": kind
        })
        save_config(config)

def unregister_plugin(prefix_path: str, plugin_name: str) -> None:
    """Unregister a plugin."""
    config = load_config()
    config["plugins"] = [p for p in config["plugins"]
                        if not (p["prefix"] == prefix_path and p["name"] == plugin_name)]
    save_config(config)

def get_total_plugin_count() -> int:
    """Get total number of registered plugins."""
    config = load_config()
    return len(config["plugins"])

def get_plugins_by_prefix(prefix_path: str) -> list[dict[str, Any]]:
    """Get all plugins in a specific prefix."""
    config = load_config()
    return [p for p in config["plugins"] if p["prefix"] == prefix_path]

def is_dxvk_installed(prefix_path: str) -> bool:
    """Check if DXVK is registered for a prefix."""
    config = load_config()
    for prefix in config["prefixes"]:
        if prefix["path"] == prefix_path:
            return prefix.get("dxvk_installed", False)
    return False

def update_prefix_dxvk(prefix_path: str, dxvk_installed: bool) -> None:
    """Update DXVK status for a prefix."""
    config = load_config()
    for prefix in config["prefixes"]:
        if prefix["path"] == prefix_path:
            prefix["dxvk_installed"] = dxvk_installed
            save_config(config)
            return

def ensure_config_dir():
    """Ensure config directory exists."""
    print(f"DEBUG: Ensuring config dir at {CONFIG_DIR}")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"DEBUG: Config dir exists: {CONFIG_DIR.exists()}")
