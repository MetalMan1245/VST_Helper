# tests/test_config.py
import pytest
from pathlib import Path

from vst_helper.config import (
    Config, ConfigError, Runner, Prefix, Plugin, validate, SCHEMA_VERSION,
)

@pytest.fixture
def cfg(tmp_path):
    """A Config pointed at a throwaway directory — never touches the real one."""
    return Config(dir=tmp_path)

def _populated(cfg):
    cfg.runners.append(Runner(name="test-wine",
                              path=Path("/fake/wine-9.21/bin/wine")))
    cfg.prefixes["main"] = Prefix(name="main", runner="test-wine")
    cfg.plugins["Fenrir Mini"] = Plugin(
        name="Fenrir Mini", format="vst3", prefix="main")
    return cfg

def test_roundtrip_preserves_everything(cfg):
    _populated(cfg)
    cfg.save()

    reloaded = Config.load(cfg.dir)
    assert reloaded.plugins["Fenrir Mini"].format == "vst3"
    assert reloaded.prefixes["main"].runner == "test-wine"

def test_load_on_empty_dir_gives_valid_empty_config(tmp_path):
    cfg = Config.load(tmp_path)   # no files at all yet — first-run scenario
    assert not cfg.prefixes and not cfg.plugins

def test_unknown_prefix_reference_is_rejected(cfg):
    _populated(cfg)
    cfg.plugins["Fenrir Mini"].prefix = "does-not-exist"
    with pytest.raises(ConfigError, match="unknown prefix 'does-not-exist'"):
        cfg.save()   # save must refuse to persist an invalid state

def test_group_spanning_prefixes_is_rejected(cfg):
    _populated(cfg)
    cfg.prefixes["quarantine"] = Prefix(name="quarantine", runner="test-wine")
    cfg.plugins["Bad Plugin"] = Plugin(
        name="Bad Plugin", format="vst2", prefix="quarantine")
    cfg.plugins["Bad Plugin"].group = cfg.plugins["Fenrir Mini"].group  # "default"
    with pytest.raises(ConfigError, match="spans prefixes"):
        cfg.save()

def test_future_schema_refuses_to_load(tmp_path):
    (tmp_path / "app.toml").write_text(f"schema_version = {SCHEMA_VERSION + 1}\n")
    with pytest.raises(ConfigError, match="newer VST Helper"):
        Config.load(tmp_path)

def test_adopted_prefix_keeps_explicit_path(tmp_path):
    _populated(cfg := Config(dir=tmp_path))
    cfg.prefixes["adopted"] = Prefix(
        name="adopted", runner="test-wine", path=Path("/mnt/some/existing/prefix"))
    cfg.save()
    reloaded = Config.load(tmp_path)
    assert reloaded.prefixes["adopted"].path == Path("/mnt/some/existing/prefix")

def test_save_creates_all_four_files(cfg):
    _populated(cfg)
    cfg.save()
    names = {p.name for p in cfg.dir.iterdir()}
    assert {"app.toml", "runners.toml", "prefixes.toml", "plugins.toml"} <= names

def test_runner_kind_and_umu_path_survive_roundtrip(cfg):
    from vst_helper.config import RunnerKind
    cfg.runners.append(Runner(
        name="proton-test",
        path=Path("/proton/dist/bin/wine"),
        kind=RunnerKind.UMU,
        umu_path=Path("/usr/bin/umu-run"),
    ))
    cfg.save()
    reloaded = Config.load(cfg.dir)
    proton = next(r for r in reloaded.runners if r.name == "proton-test")
    assert proton.kind is RunnerKind.UMU
    assert proton.umu_path == Path("/usr/bin/umu-run")

def test_skips_nonexistent_wine_gracefully(tmp_path):
    # glob can't produce this, but discover_all()'s PATH probe can hit
    # dangling entries — verify() must raise ConfigError, not FileNotFoundError
    from vst_helper.config import Runner
    r = Runner(name="ghost", path=tmp_path / "missing" / "wine")
    with pytest.raises(ConfigError):
        r.verify()
