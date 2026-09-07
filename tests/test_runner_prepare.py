# tests/test_runner_prepare.py
from pathlib import Path
import os
from vst_helper.config import Runner, RunnerKind, ConfigError

def test_plain_wine_prepares_loader_and_path_pair():
    r = Runner(name="w", path=Path("/x/bin/wine"))
    argv, env = r.prepare(["some.exe"], Path("/pfx"))
    assert argv == ["/x/bin/wine", "some.exe"]
    assert env["WINELOADER"] == "/x/bin/wine"
    assert env["PATH"].startswith("/x/bin:")
    assert env["WINEPREFIX"] == "/pfx"

def test_umu_runner_passes_wine_via_env():
    r = Runner(name="p", path=Path("/proton/dist/bin/wine"),
               kind=RunnerKind.UMU, umu_path=Path("/usr/bin/umu-run"))
    argv, env = r.prepare(["some.exe"], Path("/pfx"))
    assert argv == ["/usr/bin/umu-run", "some.exe"]
    assert env["WINE"] == "/proton/dist/bin/wine"
    assert "WINELOADER" not in env  # umu owns loader resolution

def test_umu_without_umu_path_is_rejected():
    r = Runner(name="bad", path=Path("/p/dist/bin/wine"), kind=RunnerKind.UMU)
    try:
        r.prepare(["x"])
    except ConfigError:
        pass
    else:
        raise AssertionError("expected ConfigError for missing umu_path")
