# vst_helper/config.py
"""
VST Helper — configuration module.

All persisted state lives in ~/.config/vst-helper/ as TOML:
  app.toml      — general application settings
  prefixes.toml — wine prefix definitions
  plugins.toml  — registered Windows plugins
  runners.toml  — discovered/pinned wine runners

Design principles (from the design discussion):
  - The directory layout embodies prefix assignment; this registry only *mirrors*
    physical reality, it never overrides it.
  - yabridge.toml / .desktop files are *generated artifacts*, not state.
  - Unknown keys are warn-and-preserved so older configs survive app upgrades.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tomllib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from enum import Enum

import tomli_w

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

CONFIG_DIR = Path("~/.config/vst-helper").expanduser()


class ConfigError(Exception):
    """Raised for violations the GUI layer should surface to the user."""

class RunnerKind(Enum):
    WINE = "wine"      # direct wine binary (system, Heroic, Lutris, downloaded)
    UMU = "umu"        # Proton build launched through umu-run

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Runner:
    name: str
    path: Path                     # real wine binary in both cases
    kind: RunnerKind = RunnerKind.WINE
    umu_path: Path | None = None   # only for UMU: path to umu-run

    @property
    def bindir(self) -> Path:
        """Directory containing this wine — must go into PATH alongside WINELOADER."""
        return self.path.parent

    def verify(self) -> str:
        """Return `wine --version` output, raising if the binary is unusable."""
        if not self.path.is_file():
            raise ConfigError(f"Runner '{self.name}': {self.path} does not exist")
        result = subprocess.run(
            [str(self.path), "--version"], capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ConfigError(f"Runner {self.name} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    def prepare(self, args: list[str], prefix: Path | None = None) -> tuple[list[str], dict[str, str]]:
        """Build (argv, env) to run `args` under this runner inside `prefix`.

        The env INHERITS the caller's environment (DISPLAY, WAYLAND_DISPLAY,
        HOME, ...) and layers the runner-specific overrides on top — never
        the reverse. GUI processes (plugin installers) die without a
        display server, which is exactly what wholesale env replacement
        causes.
        """
        env = dict(os.environ)

        if prefix is not None:
            env["WINEPREFIX"] = str(prefix)

        if self.kind is RunnerKind.WINE:
            argv = [str(self.path), *args]
            # Both WINELOADER and the sibling bin dir in PATH, always as a pair
            env["WINELOADER"] = str(self.path)
            env["PATH"] = f"{self.bindir}:{env.get('PATH', '')}"
        elif self.kind is RunnerKind.UMU:
            if self.umu_path is None:
                raise ConfigError(f"Runner '{self.name}' is umu-kind but has no umu-run path")
            argv = [str(self.umu_path), *args]
            env["WINE"] = str(self.path)
        else:
            raise ConfigError(f"Unknown runner kind: {self.kind}")

        return argv, env


@dataclass
class Prefix:
    """One Wine prefix. `path` is omitted for managed prefixes, which physically
    live under windows_plugin_root/<name>/ — the path IS the assignment."""
    name: str
    runner: str                # Runner.name
    arch: str = "win64"        # win64 | win32
    dxvk: bool = False
    winetricks_verbs: list[str] = field(default_factory=list)
    dll_overrides: dict[str, str] = field(default_factory=dict)
    path: Path | None = None   # only set for adopted/pre-existing prefixes

    def resolve_path(self, root: Path) -> Path:
        return self.path if self.path else root / self.name

    def exists(self) -> bool:
        root = Path("~/Games/WindowsPlugins").expanduser()
        return (self.resolve_path(root) / "drive_c").is_dir()


@dataclass
class Plugin:
    """A registered Windows plugin."""
    name: str
    format: str                      # vst3 | vst2 | clap | lv2
    prefix: str
    group: str = "default"
    installer: Path | None = None    # None => portable bundle, copied directly
    fixes_applied: list[str] = field(default_factory=list)
    yabridge_options: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    import tomllib
    with path.open("rb") as f:
        return tomllib.load(f)


def _save_toml(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(data, f)


# ---------------------------------------------------------------------------
# Migration / forward-compat
# ---------------------------------------------------------------------------

def check_schema(data: dict, name: str) -> None:
    """Warn-and-preserve: never reject unknown keys; only hard-fail on versions
    from the future (we can't interpret them safely)."""
    version = data.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        raise ConfigError(
            f"{name} was written by a newer VST Helper "
            f"(schema v{version}, this build supports v{SCHEMA_VERSION})"
        )
    if version < SCHEMA_VERSION:
        log.info("%s: upgrading schema v%d -> v%d", name, version, SCHEMA_VERSION)


def migrate(data: dict, name: str) -> dict:
    """Upgrade older schema versions in place. v1 is the baseline, so this is
    currently a no-op — future migrations chain here."""
    check_schema(data, name)
    migrated = {**data, "schema_version": SCHEMA_VERSION}
    return migrated


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

KNOWN_FORMATS = {"vst3", "vst2", "clap", "lv2"}


def validate(config: "Config") -> None:
    """Enforce cross-file invariants. Violations here are user-visible errors,
    never silent runtime weirdness."""
    runner_names = {r.name for r in config.runners}
    prefix_ids = set(config.prefixes)

    for pid, prefix in config.prefixes.items():
        if prefix.runner not in runner_names:
            raise ConfigError(
                f"Prefix '{pid}' references unknown runner '{prefix.runner}'"
            )

    for name, plugin in config.plugins.items():
        if plugin.prefix not in prefix_ids:
            raise ConfigError(
                f"Plugin '{name}' references unknown prefix '{plugin.prefix}'"
            )
        if plugin.format not in KNOWN_FORMATS:
            raise ConfigError(
                f"Plugin '{name}' has unknown format '{plugin.format}'"
            )
        # The invariant: same group => same prefix.
        # Different groups may coexist within one prefix.
        members = {
            n: p
            for n, p in config.plugins.items()
            if p.group == plugin.group
        }
        other_prefixes = {p.prefix for p in members.values()} - {plugin.prefix}
        if other_prefixes:
            raise ConfigError(
                f"Group '{plugin.group}' spans prefixes {sorted(other_prefixes | {plugin.prefix})}; "
                f"a group must live in exactly one prefix"
            )


# ---------------------------------------------------------------------------
# Top-level config object
# ---------------------------------------------------------------------------

@dataclass
class Config:
    app: dict = field(default_factory=dict)      # free-form app.toml section
    runners: list[Runner] = field(default_factory=list)
    prefixes: dict[str, Prefix] = field(default_factory=dict)
    plugins: dict[str, Plugin] = field(default_factory=dict)
    dir: Path = CONFIG_DIR

    @classmethod
    def load(cls, config_dir: Path | None = None) -> "Config":
        d = config_dir or CONFIG_DIR
        config = cls(dir=d)
        config.app = migrate(_load_toml(d / "app.toml"), "app.toml")
        for name, data in _load_toml(d / "runners.toml").get("runners", {}).items():
            umu = data.get("umu_path")
            config.runners.append(
                Runner(
                    name=name,
                    path=Path(data["path"]).expanduser(),
                    kind=RunnerKind(data.get("kind", "wine")),
                    umu_path=Path(umu).expanduser() if umu else None,
                )
            )
        for name, data in _load_toml(d / "prefixes.toml").get("prefixes", {}).items():
            path_val = data.get("path")
            config.prefixes[name] = Prefix(
                name=name,
                runner=data["runner"],
                arch=data.get("arch", "win64"),
                dxvk=data.get("dxvk", False),
                winetricks_verbs=data.get("winetricks_verbs", []),
                dll_overrides=data.get("dll_overrides", {}),
                path=Path(data["path"]) if path_val else None,
            )
        for name, data in _load_toml(d / "plugins.toml").get("plugins", {}).items():
            installer = data.get("installer")
            config.plugins[name] = Plugin(
                name=name,
                format=data["format"],
                prefix=data["prefix"],
                group=data.get("group", "default"),
                installer=Path(installer) if installer else None,
                fixes_applied=data.get("fixes_applied", []),
                yabridge_options=data.get("yabridge_options", {}),
            )
        validate(config)
        return config

    def save(self) -> None:
        validate(self)  # never persist an invalid state
        _save_toml({**self.app, "schema_version": SCHEMA_VERSION}, self.dir / "app.toml")
        _save_toml(
            {
                "schema_version": SCHEMA_VERSION,
                "runners": {
                    r.name: {
                        "path": str(r.path),
                        "kind": r.kind.value,
                        **({"umu_path": str(r.umu_path)} if r.umu_path else {}),
                    }
                    for r in self.runners
                },
            },
            self.dir / "runners.toml",
        )
        _save_toml(
            {
                "schema_version": SCHEMA_VERSION,
                "prefixes": {
                    pid: prefix_to_toml(p) for pid, p in self.prefixes.items()
                },
            },
            self.dir / "prefixes.toml",
        )
        _save_toml(
            {
                "schema_version": SCHEMA_VERSION,
                "plugins": {
                    n: plugin_to_toml(p) for n, p in self.plugins.items()
                },
            },
            self.dir / "plugins.toml",
        )


def prefix_to_toml(p: Prefix) -> dict:
    out: dict = {"runner": p.runner, "arch": p.arch, "dxvk": p.dxvk}
    if p.winetricks_verbs:
        out["winetricks_verbs"] = p.winetricks_verbs
    if p.dll_overrides:
        out["dll_overrides"] = dict(p.dll_overrides)
    if p.path is not None:
        out["path"] = str(p.path)
    return out


def plugin_to_toml(p: Plugin) -> dict:
    out: dict = {"format": p.format, "prefix": p.prefix, "group": p.group}
    if p.installer is not None:
        out["installer"] = str(p.installer)
    if p.fixes_applied:
        out["fixes_applied"] = list(p.fixes_applied)
    if p.yabridge_options:
        out["yabridge_options"] = dict(p.yabridge_options)
    return out
