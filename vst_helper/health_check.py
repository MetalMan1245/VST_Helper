"""Health checks for Wine, yabridge, realtime kernel, and audio setup."""

import os
import shutil
import pwd
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


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
    """Check if Wine is available."""
    wine_binaries = []

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
        return HealthCheckResult(
            component="Wine",
            status=HealthStatus.OK,
            message=f"Wine found: {wine_binaries[0][0]} ({wine_binaries[0][1]})",
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


def check_yabridge() -> HealthCheckResult:
    """Check if yabridge and yabridgectl are installed."""
    # Check standard PATH first
    yabridge = shutil.which("yabridge")
    yabridgectl = shutil.which("yabridgectl")

    # Also check common alternate names (some packages install as just 'yabridgectl')
    if not yabridgectl:
        yabridgectl = shutil.which("yabridgctl")  # typo variant

    if yabridge and yabridgectl:
        return HealthCheckResult(
            component="yabridge",
            status=HealthStatus.OK,
            message=f"yabridge ({yabridge}) and yabridgectl ({yabridgectl}) found",
            required=False
        )

    if yabridge:
        return HealthCheckResult(
            component="yabridge",
            status=HealthStatus.WARNING,
            message=f"yabridge found ({yabridge}), but yabridgectl missing. Both required for plugin management.",
            required=False
        )

    if yabridgectl:
        return HealthCheckResult(
            component="yabridge",
            status=HealthStatus.WARNING,
            message=f"yabridgectl found ({yabridgectl}), but yabridge binary missing. Both required.",
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
    current_user = os.environ.get("USER", "")

    try:
        realtime_gid = pwd.getpwnam("realtime").pw_gid
        with open("/etc/group", "r") as f:
            for line in f:
                if line.startswith("realtime:"):
                    members = line.strip().split(":")[-1].split(",")
                    if current_user in members:
                        return HealthCheckResult(
                            component="Realtime Group",
                            status=HealthStatus.OK,
                            message=f"User '{current_user}' is in realtime group",
                            required=False
                        )
    except (KeyError, FileNotFoundError):
        pass

    return HealthCheckResult(
        component="Realtime Group",
        status=HealthStatus.WARNING,
        message="User not in realtime group. Low-latency audio may not work correctly.",
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


def run_full_health_check(for_windows_plugin: bool = False) -> List[HealthCheckResult]:
    """Run all health checks and return results."""
    results = []

    # Always check these
    results.append(check_wine(required_for_operation=for_windows_plugin))
    results.append(check_yabridge())
    results.append(check_realtime_group())
    results.append(check_realtime_kernel())

    return results
