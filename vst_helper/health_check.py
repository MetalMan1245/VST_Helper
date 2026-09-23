"""Health checks for Wine, yabridge, realtime kernel, and audio setup."""

import os
import shutil
import pwd
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

def detect_distro() -> str:
    """Detect Linux distribution family."""
    try:
        with open("/etc/os-release", "r") as f:
            content = f.read().lower()
        if "fedora" in content:
            return "fedora"
        elif "debian" in content or "ubuntu" in content or "linuxmint" in content:
            return "debian"
        else:
            return "arch"
    except FileNotFoundError:
        return "unknown"

def get_install_command(pkg_name: str, distro: str) -> str | None:
    """Return the appropriate install command for a package."""
    commands = {
        "arch": f"sudo pacman -S --noconfirm {pkg_name}",
        "debian": f"sudo apt install -y {pkg_name}",
        "fedora": f"sudo dnf install -y {pkg_name}",
    }
    return commands.get(distro)

def run_privileged_command(command: str) -> tuple[bool, str]:
    """Run a command with privilege escalation via pkexec."""
    from subprocess import run
    try:
        result = run(["pkexec", "sh", "-c", command], capture_output=True, text=True, timeout=60)
        return result.returncode == 0, result.stderr or result.stdout
    except FileNotFoundError:
        return False, "pkexec not found"
    except Exception as e:
        return False, str(e)


class HealthStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"  # Not required for current operation


@dataclass
class HealthCheckResult:
    component: str
    status: HealthStatus
    message: str
    required: bool = True  # If False, only warn, don't block


def check_wine(required_for_operation: bool = False) -> HealthCheckResult:
    """Check if Wine is available (pinned preferred, then fallbacks)."""
    from .wine_manager import is_pinned_installed, PINNED_VERSION, pinned_wine_binary

    wine_binaries = []

    # Check pinned app-managed Wine first
    if is_pinned_installed():
        wine_binaries.append(("pinned", str(pinned_wine_binary())))

    # Check system Wine
    system_wine = shutil.which("wine")
    if system_wine:
        wine_binaries.append(("system", system_wine))

    # Check Heroic Wine
    heroic_path = Path("~/.config/heroic/tools/wine").expanduser()
    if heroic_path.exists():
        found = sorted(heroic_path.glob("*/*/bin/wine"))
        if found:
            wine_binaries.append(("heroic", str(found[0])))

    # Check system-provided Wine (CachyOS packages)
    cachyos_wine = shutil.which("cachyos-wine")
    if cachyos_wine:
        wine_binaries.append(("cachyos", cachyos_wine))

    if wine_binaries:
        # Warn if not using pinned version
        is_pinned = wine_binaries[0][0] == "pinned"
        status = HealthStatus.OK if is_pinned else HealthStatus.WARNING
        message = f"Wine found: {wine_binaries[0][0]} ({wine_binaries[0][1]})"
        if not is_pinned:
            message += f" (pinned Wine {PINNED_VERSION} recommended)"
        return HealthCheckResult(
            component="Wine",
            status=status,
            message=message,
            required=False
        )

    return HealthCheckResult(
        component="Wine",
        status=HealthStatus.ERROR if required_for_operation else HealthStatus.WARNING,
        message="No Wine installation detected. Windows plugins will not work.",
        required=required_for_operation
    )

def check_wine_version(wine_runner: Path, target_version: str = "9.21") -> HealthCheckResult:
    """Check Wine version (best-effort)."""
    try:
        result = subprocess.run(
            [str(wine_runner), "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )

        version_output = result.stdout.strip()
        if target_version in version_output:
            return HealthCheckResult(
                component="Wine Version",
                status=HealthStatus.OK,
                message=f"Wine version: {version_output}",
                required=False
            )

        return HealthCheckResult(
            component="Wine Version",
            status=HealthStatus.WARNING,
            message=f"Wine version: {version_output} (recommended: {target_version})",
            required=False
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return HealthCheckResult(
            component="Wine Version",
            status=HealthStatus.SKIPPED,
            message="Could not determine Wine version",
            required=False
        )

def check_pinned_wine() -> HealthCheckResult:
    """Check if the app-managed Wine 9.21 is installed."""
    from .wine_manager import is_pinned_installed, PINNED_VERSION, pinned_wine_binary

    if is_pinned_installed():
        return HealthCheckResult(
            component="Pinned Wine",
            status=HealthStatus.OK,
            message=f"Wine {PINNED_VERSION} installed (recommended for yabridge)",
            required=False
        )

    return HealthCheckResult(
        component="Pinned Wine",
        status=HealthStatus.WARNING,
        message=f"Wine {PINNED_VERSION} not installed. Install from Settings → Advanced for consistent yabridge behavior.",
        required=False
    )

def check_yabridge() -> HealthCheckResult:
    """Check if yabridge and yabridgectl are installed."""
    yabridge = shutil.which("yabridge")
    yabridgectl = shutil.which("yabridgectl")

    if not yabridgectl:
        yabridgectl = shutil.which("yabridgctl")

    # Also check common alternate locations
    if not yabridge:
        for alt_path in [
            Path("~/.local/bin").expanduser() / "yabridge",
            Path("/usr/local/bin") / "yabridge",
        ]:
            if alt_path.exists():
                yabridge = str(alt_path)
                break

    if not yabridgectl:
        for alt_path in [
            Path("~/.local/bin").expanduser() / "yabridgectl",
            Path("/usr/local/bin") / "yabridgectl",
        ]:
            if alt_path.exists():
                yabridgectl = str(alt_path)
                break

    if yabridge and yabridgectl:
        return HealthCheckResult(
            component="yabridge",
            status=HealthStatus.OK,
            message=f"yabridge ({yabridge}) and yabridgectl ({yabridgectl}) found",
            required=False
        )

    if yabridge and not yabridgectl:
        return HealthCheckResult(
            component="yabridge",
            status=HealthStatus.WARNING,
            message=f"yabridge found ({yabridge}), but yabridgectl missing",
            required=False
        )

    if yabridgectl and not yabridge:
        return HealthCheckResult(
            component="yabridge",
            status=HealthStatus.WARNING,
            message=f"yabridgectl found ({yabridgectl}), but yabridge missing",
            required=False
        )

    return HealthCheckResult(
        component="yabridge",
        status=HealthStatus.WARNING,
        message="yabridge not installed. Windows plugins will not appear in your DAW.",
        required=False
    )

def check_realtime_group() -> HealthCheckResult:
    """Check if current user is in the realtime group."""
    import grp

    current_user = os.environ.get("USER", "")

    try:
        realtime_group = grp.getgrnam("realtime")
        # Check both gr_mem and primary group ID
        uid = os.getuid()
        user_info = pwd.getpwuid(uid)

        if current_user in realtime_group.gr_mem or user_info.pw_gid == realtime_group.gr_gid:
            return HealthCheckResult(
                component="Realtime Group",
                status=HealthStatus.OK,
                message=f"User '{current_user}' is in realtime group (gid {realtime_group.gr_gid})",
                required=False
            )
        else:
            return HealthCheckResult(
                component="Realtime Group",
                status=HealthStatus.WARNING,
                message=f"User '{current_user}' is not in realtime group. Low-latency audio may not work correctly.",
                required=False
            )
    except KeyError:
        return HealthCheckResult(
            component="Realtime Group",
            status=HealthStatus.WARNING,
            message="Realtime group does not exist. Create it: sudo groupadd realtime && sudo usermod -aG realtime $USER",
            required=False
        )

def check_dxvk(prefix_path: Path, runner_path: Path | None = None) -> HealthCheckResult:
    """Check if DXVK is installed and ACTIVE in a Wine prefix."""
    if not prefix_path.exists():
        return HealthCheckResult(
            component="DXVK",
            status=HealthStatus.SKIPPED,
            message=f"Prefix does not exist: {prefix_path}",
            required=False
        )

    dxvk_dll = prefix_path / "drive_c" / "windows" / "system32" / "dxgi.dll"

    if not dxvk_dll.exists():
        return HealthCheckResult(
            component="DXVK",
            status=HealthStatus.WARNING,
            message=f"DXVK not installed in {prefix_path.name}. Recommended for better Windows plugin performance.",
            required=False
        )

    # DLLs present, but check whether overrides make them active
    if runner_path is not None:
        import subprocess, os
        env = dict(os.environ, WINEPREFIX=str(prefix_path))
        try:
            result = subprocess.run(
                [str(runner_path), "reg", "query",
                 "HKCU\\Software\\Wine\\DllOverrides"],
                env=env, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and "dxgi" in result.stdout and "native" in result.stdout:
                return HealthCheckResult(
                    component="DXVK",
                    status=HealthStatus.OK,
                    message=f"DXVK installed and active in {prefix_path.name}",
                    required=False
                )
            return HealthCheckResult(
                component="DXVK",
                status=HealthStatus.WARNING,
                message=f"DXVK DLLs present in {prefix_path.name} but not active (missing registry overrides).",
                required=False
            )
        except Exception as e:
            return HealthCheckResult(
                component="DXVK",
                status=HealthStatus.WARNING,
                message=f"DXVK DLLs present but could not verify activation: {e}",
                required=False
            )

    return HealthCheckResult(
        component="DXVK",
        status=HealthStatus.WARNING,
        message=f"DXVK DLLs present in {prefix_path.name} (could not verify activation).",
        required=False
    )

def check_realtime_kernel() -> HealthCheckResult:
    """Check if running a realtime/preempt kernel."""
    try:
        result = subprocess.run(
            ["uname", "-r"],
            capture_output=True,
            text=True,
            timeout=5
        )

        kernel = result.stdout.strip()
        kernel_lower = kernel.lower()

        if "rt" in kernel_lower or "preempt" in kernel_lower or "zen" in kernel_lower:
            return HealthCheckResult(
                component="Kernel",
                status=HealthStatus.OK,
                message=f"Running {kernel} (good for real-time audio)",
                required=False
            )

        return HealthCheckResult(
            component="Kernel",
            status=HealthStatus.WARNING,
            message=f"Running {kernel} (consider PREEMPT_RT or Zen kernel for low-latency audio)",
            required=False
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return HealthCheckResult(
            component="Kernel",
            status=HealthStatus.SKIPPED,
            message="Could not determine kernel version",
            required=False
        )


def run_full_health_check(for_windows_plugin: bool = False, prefix_path: Path | None = None) -> list[HealthCheckResult]:
    """Run all health checks and return results."""
    results = []

    results.append(check_wine(required_for_operation=for_windows_plugin))
    results.append(check_yabridge())
    results.append(check_realtime_group())
    results.append(check_realtime_kernel())
    results.append(check_pinned_wine())

    if prefix_path:
        results.append(check_dxvk(prefix_path))

    return results
