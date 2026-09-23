"""Settings dialog for VST Helper."""

import shutil
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from .config import Runner
from .health_check import (
    run_full_health_check, HealthCheckResult, HealthStatus, check_dxvk,
    detect_distro, get_install_command, run_privileged_command,
)
from .plugin_installer import sync_yabridge, add_sync_targets
from .prefix_manager import create_prefix
from .gui_main import DEFAULT_PREFIX, resolve_runner
from .wine_manager import PINNED_VERSION, is_pinned_installed
from .reaper_config import modify_reaper_exec_with_wine

class DXVKInstallWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, prefix_path: Path, runner: Runner):
        super().__init__()
        self.prefix_path = prefix_path
        self.runner = runner

    def run(self):
        try:
            print("DEBUG: Starting DXVK installation worker")
            self.progress.emit("Downloading DXVK...")
            from urllib.request import urlretrieve
            import tempfile
            import tarfile

            latest_url = "https://github.com/doitsujin/dxvk/releases/download/v1.10.1/dxvk-1.10.1.tar.gz"

            with tempfile.TemporaryDirectory() as tmpdir:
                archive_path = Path(tmpdir) / "dxvk.tar.gz"
                self.progress.emit("Downloading DXVK archive...")
                print(f"DEBUG: Downloading to {archive_path}")

                try:
                    urlretrieve(latest_url, str(archive_path))
                except Exception as e:
                    print(f"DEBUG: Download failed: {e}")
                    raise Exception(f"Failed to download DXVK: {e}")

                print(f"DEBUG: Archive downloaded: {archive_path.exists()}, size={archive_path.stat().st_size if archive_path.exists() else 0}")

                self.progress.emit("Extracting DXVK...")
                with tarfile.open(str(archive_path), "r:gz") as tar:
                    members = tar.getmembers()
                    print(f"DEBUG: Archive contains {len(members)} files")
                    tar.extractall(tmpdir)

                extracted = list(Path(tmpdir).glob("dxvk-*"))
                print(f"DEBUG: Extracted directories: {extracted}")
                if not extracted:
                    raise Exception("Failed to extract DXVK archive")

                dxvk_dir = extracted[0]
                x64_files = dxvk_dir / "x64"
                print(f"DEBUG: x64 dir exists: {x64_files.exists()}")

                if not x64_files.exists():
                    raise Exception("DXVK x64 files not found in archive")

                system32 = self.prefix_path / "drive_c" / "windows" / "system32"
                system32.mkdir(parents=True, exist_ok=True)
                print(f"DEBUG: system32 path: {system32}")

                self.progress.emit("Installing DXVK DLLs...")
                installed_count = 0
                for dll in x64_files.glob("*.dll"):
                    dst = system32 / dll.name
                    shutil.copy2(dll, dst)
                    installed_count += 1
                    self.progress.emit(f"Installed {dll.name}")

                print(f"DEBUG: Installed {installed_count} DLLs")

            # Set DLL overrides so Wine actually loads the native DXVK DLLs
            self.progress.emit("Setting DLL overrides...")
            import os as _os
            from subprocess import run as sp_run

            env = dict(_os.environ, WINEPREFIX=str(self.prefix_path))
            for dll in ("d3d9", "d3d10core", "d3d11", "dxgi"):
                result = sp_run(
                    [str(self.runner.path), "reg", "add",
                     "HKCU\\Software\\Wine\\DllOverrides",
                     "/v", dll, "/t", "REG_SZ", "/d", "native", "/f"],
                    env=env, capture_output=True, text=True, timeout=120)
                if result.returncode != 0:
                    raise Exception(
                        f"Failed to set DLL override for {dll}: {result.stderr}")
                self.progress.emit(f"Override set: {dll}=native")

            # Register DXVK installation
            from .config_manager import update_prefix_dxvk
            update_prefix_dxvk(str(self.prefix_path), True)
            print(f"DEBUG: Updated config for DXVK status")

            self.progress.emit("Syncing yabridge...")
            add_sync_targets(self.runner, [self.prefix_path])
            sync_yabridge(self.runner)

            self.done.emit(True, f"DXVK installed successfully ({installed_count} DLLs)")
        except Exception as e:
            print(f"DEBUG: DXVK install failed: {e}")
            import traceback
            traceback.print_exc()
            self.done.emit(False, str(e))


class SettingsDialog(QDialog):
    refresh_triggered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("VST Helper — Settings")
        self.setMinimumWidth(550)
        self.resize(600, 500)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # Health tab
        health_tab = QWidget()
        health_layout = QVBoxLayout(health_tab)

        health_header = QLabel("<h3>System Health Check</h3>")
        health_layout.addWidget(health_header)

        self.health_output = QTextEdit(readOnly=True)
        self.health_output.setMinimumHeight(150)
        health_layout.addWidget(self.health_output)

        health_buttons = QHBoxLayout()
        refresh_btn = QPushButton("Run Health Check")
        refresh_btn.clicked.connect(self._run_health_check)
        health_buttons.addWidget(refresh_btn)

        repair_btn = QPushButton("Auto-Fix Issues")
        repair_btn.clicked.connect(self._auto_fix_issues)
        health_buttons.addWidget(repair_btn)

        health_buttons.addStretch()
        health_layout.addLayout(health_buttons)

        tabs.addTab(health_tab, "Health")

        # Prefixes tab
        prefixes_tab = QWidget()
        prefixes_layout = QVBoxLayout(prefixes_tab)

        prefix_header = QLabel("<h3>Wine Prefixes</h3>")
        prefixes_layout.addWidget(prefix_header)

        prefix_list = QLabel("Default prefix: ~/.local/share/vst-helper/prefixes/default")
        prefix_list.setStyleSheet("color: #aaa;")
        prefixes_layout.addWidget(prefix_list)

        dxvk_section = QLabel("<br/><b>DXVK Installation:</b>")
        prefixes_layout.addWidget(dxvk_section)

        dxvk_layout = QHBoxLayout()

        check_dxvk_btn = QPushButton("Check DXVK Status")
        check_dxvk_btn.clicked.connect(self._check_prefixes_dxvk)
        dxvk_layout.addWidget(check_dxvk_btn)

        install_dxvk_btn = QPushButton("Install DXVK to Default Prefix")
        install_dxvk_btn.clicked.connect(self._install_dxvk_default)
        dxvk_layout.addWidget(install_dxvk_btn)

        prefixes_layout.addLayout(dxvk_layout)

        self.dxvk_status = QLabel("DXVK status: unknown")
        self.dxvk_status.setWordWrap(True)
        self.dxvk_status.setStyleSheet("color: #aaa;")
        prefixes_layout.addWidget(self.dxvk_status)

        tabs.addTab(prefixes_tab, "Prefixes")

        # Advanced tab
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)

        advanced_header = QLabel("<h3>Advanced Options</h3>")
        advanced_layout.addWidget(advanced_header)

        note = QLabel("Advanced options allow you to customize Wine prefixes and versions.<br/>Use with caution.")
        note.setWordWrap(True)
        advanced_layout.addWidget(note)

        # Placeholder for future advanced features
        advanced_placeholder = QLabel("Coming soon: Custom prefix paths, Wine version selection")
        advanced_placeholder.setStyleSheet("color: #888; font-style: italic;")
        advanced_layout.addWidget(advanced_placeholder)

        tabs.addTab(advanced_tab, "Advanced")

        layout.addWidget(tabs)

        wine_pin_btn = QPushButton(f"Install Wine {PINNED_VERSION} (recommended for yabridge)")
        wine_pin_btn.clicked.connect(self._install_pinned_wine)
        advanced_layout.addWidget(wine_pin_btn)

        self.wine_pin_status = QLabel(
            f"Wine {PINNED_VERSION}: installed" if is_pinned_installed()
            else f"Wine {PINNED_VERSION}: not installed"
        )
        self.wine_pin_status.setWordWrap(True)
        self.wine_pin_status.setStyleSheet("color: #aaa;")
        advanced_layout.addWidget(self.wine_pin_status)

        self.reaper_config_btn = QPushButton("Configure REAPER Wine Runner")
        self.reaper_config_btn.setEnabled(is_pinned_installed())
        self.reaper_config_btn.clicked.connect(self._configure_reaper)
        advanced_layout.addWidget(self.reaper_config_btn)

    def _configure_reaper(self):
        from .wine_manager import pinned_wine_binary
        from .reaper_config import modify_reaper_exec_with_wine, get_reaper_desktop_path, pick_reaper_desktop_fallback

        wine_path = pinned_wine_binary()
        if not wine_path.exists():
            QMessageBox.warning(
                self, "Wine Required",
                f"Install Wine {PINNED_VERSION} first.")
            return

        # Try automatic discovery first
        reaper_desktop = get_reaper_desktop_path()

        if not reaper_desktop:
            # Ask user if they want to pick manually
            reply = QMessageBox.question(
                self, "REAPER .desktop Not Found",
                "Could not find REAPER .desktop file automatically.\n\n"
                "Search path included:\n"
                "- /usr/share/applications/\n"
                "- ~/.local/share/applications/\n\n"
                "Common filename: cockos-reaper.desktop\n\n"
                "Would you like to select it manually?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)

            if reply == QMessageBox.StandardButton.Yes:
                reaper_desktop = pick_reaper_desktop_fallback()
                if not reaper_desktop:
                    QMessageBox.information(
                        self, "Cancelled",
                        "Operation cancelled. You can retry from Settings → Advanced later.")
                    return
            else:
                QMessageBox.information(
                    self, "Skipped",
                    "You can configure REAPER manually by editing:\n"
                    "/usr/share/applications/cockos-reaper.desktop (or similar)\n\n"
                    "Add WINE=/path/to/wine before the existing Exec command.")
                return

        # Attempt modification (may require pkexec)
        success, msg = modify_reaper_exec_with_wine(wine_path)

        if success:
            QMessageBox.information(
                self, "REAPER Configured",
                f"Modified: {msg}\n\n"
                f"Added: env WINELOADER={wine_path} to Exec line\n\n"
                "Next steps:\n"
                "1. Logout/login to reload menu entries\n"
                "2. rm -rf ~/.local/share/vst-helper/prefixes/default\n"
                "3. Reinstall DXVK from Settings → Prefixes\n"
                "4. Launch REAPER from application menu (not terminal)")
        else:
            QMessageBox.critical(
                self, "Configuration Failed",
                f"Failed to modify REAPER .desktop: {msg}\n\n"
                f"Target file: {reaper_desktop}")

    def _pinned_wine_done(self, success: bool, message: str):
        self.wine_pin_btn.setEnabled(True)
        if success:
            self.wine_pin_status.setText(message)
            self.reaper_config_btn.setEnabled(True)

            QMessageBox.information(
                self, "Wine Installed",
                message + ".\n\n"
                "Click 'Configure REAPER Wine Runner' to apply.")
        else:
            self.wine_pin_status.setText(f"Failed: {message}")
            QMessageBox.critical(self, "Wine Install Failed", message)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # Run initial health check
        self._run_health_check()

    def _log_health(self, message: str):
        self.health_output.append(message)

    def _run_health_check(self):
        self.health_output.clear()
        self._log_health("Running health check...")

        results = run_full_health_check()

        for r in results:
            icons = {"ok": "✓", "warning": "⚠", "error": "✗", "skipped": "○"}
            icon = icons.get(r.status.value, "?")
            self._log_health(f"{icon} {r.component}: {r.message}")

        self._log_health("")
        self._log_health("Health check complete.")

        # Also check prefixes for DXVK
        self._log_health("Checking prefixes for DXVK...")
        default_prefix = DEFAULT_PREFIX
        if default_prefix.exists() and (default_prefix / "drive_c").exists():
            dxvk_result = check_dxvk(default_prefix)
            self._log_health(f"{dxvk_result.status.value.upper()}: {dxvk_result.message}")
        else:
            self._log_health("No default prefix found.")

    def _auto_fix_issues(self):
        from .wine_manager import install_pinned, PINNED_VERSION, is_pinned_installed

        distro = detect_distro()

        # Build list of fixes needed
        fixes = []

        # Check pinned Wine
        if not is_pinned_installed():
            fixes.append(("Pinned Wine 9.21", "download and install portable Wine 9.21"))

        # Check yabridge
        ybridge_status = check_yabridge()
        if ybridge_status.status.value != "ok":
            fixes.append(("yabridge", get_install_command("yabridge", distro)))

        # Check realtime group
        realtime_status = next((r for r in run_full_health_check() if r.component == "Realtime Group"), None)
        if realtime_status and realtime_status.status.value != "ok":
            fixes.append(("Realtime Group", "sudo usermod -aG realtime $USER"))

        # Check Wine (system)
        wine_status = check_wine(required_for_operation=True)
        if wine_status.status.value != "ok" and not is_pinned_installed():
            fixes.append(("Wine (fallback)", get_install_command("wine", distro)))

        if not fixes:
            QMessageBox.information(self, "Already Fixed", "All components are healthy!")
            return

        # Show confirmation
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Auto-Fix")
        confirm.setText(f"Fix {len(fixes)} missing component(s)?")

        fix_list = "\n".join(f"- {f[0]}" for f in fixes)
        confirm.setInformativeText(fix_list + "\n\nPinned Wine 9.21 will be downloaded automatically.")

        confirm.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        confirm.setDefaultButton(QMessageBox.StandardButton.Yes)

        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        # Execute pinned Wine install first (non-privileged, downloads)
        if not is_pinned_installed():
            self._log_health("Installing pinned Wine 9.21...")
            try:
                install_pinned(progress=self._log_health)
                self._log_health("✓ Pinned Wine 9.21 installed")
            except Exception as e:
                self._log_health(f"✗ Failed to install Wine 9.21: {e}")

        # Execute privileged fixes
        for component, cmd in fixes[1:] if len(fixes) > 1 else []:
            self._log_health(f"Running: {cmd}")
            success, output = run_privileged_command(cmd)
            if success:
                self._log_health(f"✓ {component} fixed")
            else:
                self._log_health(f"✗ Failed {component}: {output}")

        QMessageBox.information(
            self, "Auto-Fix Complete",
            "Some changes require restart/logout to take effect. "
            "If you installed Wine 9.21, delete your existing prefix "
            "and let VST Helper recreate it.")

    def _check_prefixes_dxvk(self):
        from .config_manager import load_config
        config = load_config()
        prefixes = config.get("prefixes", [])

        if not prefixes:
            self.dxvk_status.setText("DXVK status: no prefixes registered — install a Windows plugin first.")
            return

        runner = resolve_runner()
        summaries = []
        for prefix_data in prefixes:
            prefix_path = Path(prefix_data["path"])
            if prefix_path.exists() and (prefix_path / "drive_c").exists():
                runner_path = runner.path if runner else None
                result = check_dxvk(prefix_path, runner_path)
                summaries.append(f"{prefix_path.name}: {result.message}")
            else:
                summaries.append(f"{prefix_data['path']} (invalid)")

        self.dxvk_status.setText("DXVK status: " + " | ".join(summaries))

    def _install_dxvk_default(self):
        runner = resolve_runner()
        if runner is None:
            QMessageBox.warning(self, "Wine Required", "No Wine installation found.")
            return

        prefix = DEFAULT_PREFIX
        if not prefix.exists() or not (prefix / "drive_c").exists():
            QMessageBox.warning(self, "Prefix Required", "Default prefix does not exist. Create it first.")
            return

        confirm = QMessageBox(self)
        confirm.setWindowTitle("Install DXVK")
        confirm.setText("Install DXVK to default prefix?")
        confirm.setInformativeText("This will download and install DXVK to improve DirectX performance.")
        confirm.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        confirm.setDefaultButton(QMessageBox.StandardButton.Yes)

        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        print("DEBUG: Starting DXVK worker")

        # Start DXVK install worker
        self.dxvk_worker = DXVKInstallWorker(prefix, runner)
        self.dxvk_worker.progress.connect(self._log_health)
        self.dxvk_worker.done.connect(self._dxvk_install_done)
        self.dxvk_worker.start()
        print("DEBUG: DXVK worker started")

        self._log_health("Starting DXVK installation...")

    def _dxvk_install_done(self, success: bool, message: str):
        if success:
            QMessageBox.information(self, "DXVK Installed", message)
            self._log_health(f"SUCCESS: {message}")
            self._run_health_check()
        else:
            QMessageBox.critical(self, "DXVK Installation Failed", message)
            self._log_health(f"FAILED: {message}")

    def _install_pinned_wine(self):
        from .wine_manager import install_pinned
        confirm = QMessageBox(self)
        confirm.setWindowTitle(f"Install Wine {PINNED_VERSION}")
        confirm.setText(f"Download the portable Wine {PINNED_VERSION} build (~100MB)?")
        confirm.setInformativeText(
            "This is downloaded to VST Helper's own directory — your system "
            "Wine installation is not touched.")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        self.wine_pin_btn = self.sender()
        self.wine_pin_btn.setEnabled(False)
        self.wine_pin_status.setText(f"Installing Wine {PINNED_VERSION}...")

        class WineWorker(QThread):
            done = pyqtSignal(bool, str)

            def run(inner_self):
                try:
                    install_pinned(progress=print)
                    inner_self.done.emit(True, f"Wine {PINNED_VERSION} installed")
                except Exception as e:
                    inner_self.done.emit(False, str(e))

        self.wine_worker = WineWorker()
        self.wine_worker.done.connect(self._pinned_wine_done)
        self.wine_worker.start()

    def _pinned_wine_done(self, success: bool, message: str):
        self.wine_pin_btn.setEnabled(True)
        if success:
            self.wine_pin_status.setText(message)
            QMessageBox.information(
                self, "Wine Installed",
                message + ".\n\nIMPORTANT: your existing default prefix was "
                "created with a different Wine version. Delete it and let "
                "VST Helper recreate it with the pinned Wine, then reinstall "
                "DXVK and your plugins.")
        else:
            self.wine_pin_status.setText(f"Failed: {message}")
            QMessageBox.critical(self, "Wine Install Failed", message)

    def closeEvent(self, event):
        if hasattr(self, 'dxvk_worker') and self.dxvk_worker.isRunning():
            reply = QMessageBox.question(
                self, "DXVK Installing",
                "DXVK is still installing. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
        event.accept()
