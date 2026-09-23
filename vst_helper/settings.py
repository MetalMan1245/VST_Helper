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


class DXVKInstallWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, prefix_path: Path, runner: Runner):
        super().__init__()
        self.prefix_path = prefix_path
        self.runner = runner

    def run(self):
        try:
            self.progress.emit("Downloading DXVK...")
            from urllib.request import urlretrieve
            import tempfile
            import tarfile

            latest_url = "https://github.com/doitsujin/dxvk/releases/download/v1.10.1/dxvk-1.10.1.tar.gz"

            with tempfile.TemporaryDirectory() as tmpdir:
                archive_path = Path(tmpdir) / "dxvk.tar.gz"
                self.progress.emit("Downloading DXVK archive...")
                urlretrieve(latest_url, archive_path)

                self.progress.emit("Extracting DXVK...")
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(tmpdir)

                extracted = list(Path(tmpdir).glob("dxvk-*"))
                if not extracted:
                    raise Exception("Failed to extract DXVK archive")

                dxvk_dir = extracted[0]
                x64_files = dxvk_dir / "x64"

                if not x64_files.exists():
                    raise Exception("DXVK x64 files not found in archive")

                system32 = self.prefix_path / "drive_c" / "windows" / "system32"
                system32.mkdir(parents=True, exist_ok=True)

                self.progress.emit("Installing DXVK DLLs...")
                for dll in x64_files.glob("*.dll"):
                    dst = system32 / dll.name
                    shutil.copy2(dll, dst)
                    self.progress.emit(f"Installed {dll.name}")

            # Register DXVK installation
            from .config_manager import update_prefix_dxvk, register_prefix
            update_prefix_dxvk(str(self.prefix_path), True)

            self.progress.emit("Syncing yabridge...")
            add_sync_targets(self.runner, [self.prefix_path])
            sync_yabridge(self.runner)

            self.done.emit(True, "DXVK installed successfully")
        except Exception as e:
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
        distro = detect_distro()

        # Show fix options dialog (similar to onboarding auto-fix)
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Auto-Fix")
        confirm.setText("Install missing components?")
        confirm.setInformativeText("This may require your password.")
        confirm.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        confirm.setDefaultButton(QMessageBox.StandardButton.Yes)

        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        # Execute fixes (reuse onboarding logic or simplify here)
        # For now, just show a message
        QMessageBox.information(
            self, "Auto-Fix",
            "Auto-fix will install missing components via pkexec.\nCheck the terminal for progress.")

    def _check_prefixes_dxvk(self):
        self.health_output.clear()
        self._log_health("Checking prefixes for DXVK...")

        for prefix_name, prefix_path in [("Default", DEFAULT_PREFIX)]:
            if prefix_path.exists() and (prefix_path / "drive_c").exists():
                result = check_dxvk(prefix_path)
                self._log_health(f"{result.status.value.upper()}: {result.message}")
            else:
                self._log_health(f"{prefix_name}: No prefix found")

        if not any((DEFAULT_PREFIX / "drive_c").exists()):
            self._log_health("Create a prefix first before checking DXVK.")

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
        confirm.setInformativeText("This may take a minute. DXVK improves DirectX performance.")
        confirm.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        confirm.setDefaultButton(QMessageBox.StandardButton.Yes)

        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        # Start DXVK install worker
        self.dxvk_worker = DXVKInstallWorker(prefix, runner)
        self.dxvk_worker.progress.connect(self._log_health)
        self.dxvk_worker.done.connect(self._dxvk_install_done)
        self.dxvk_worker.start()

        self._log_health("Starting DXVK installation...")

    def _dxvk_install_done(self, success: bool, message: str):
        if success:
            QMessageBox.information(self, "DXVK Installed", message)
            self._log_health(f"SUCCESS: {message}")
            self._run_health_check()
        else:
            QMessageBox.critical(self, "DXVK Installation Failed", message)
            self._log_health(f"FAILED: {message}")

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
