"""Main GUI application for VST Helper."""

import shutil
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QTextEdit, QVBoxLayout, QWidget,
)

from .config import Runner
from .file_detector import FileType, detect_file_type
from .generators import write_yabridge_toml
from .health_check import (
    HealthCheckResult, run_full_health_check, check_wine, check_yabridge,
    check_dxvk, detect_distro, get_install_command, run_privileged_command,
)
from .plugin_installer import (
    add_sync_targets, find_installed_plugins, install_from_installer,
    install_portable, sync_yabridge,
)
from .prefix_manager import create_prefix, shutdown_prefix
from .health_check import HealthCheckResult, run_full_health_check, check_wine, check_yabridge

USER_DIRS = {
    "vst3": Path("~/.vst3").expanduser(),
    "clap": Path("~/.clap").expanduser(),
    "lv2": Path("~/.lv2").expanduser(),
}

LINUX_TYPES = {FileType.LINUX_VST3, FileType.LINUX_CLAP, FileType.LINUX_LV2}

DEFAULT_PREFIX = Path("~/.local/share/vst-helper/prefixes/default").expanduser()

FIRST_RUN_FLAG = (Path.home() / ".local" / "share" / "vst-helper" / ".first_launch_done")

def resolve_runner() -> Runner | None:
    """Pick a Wine: system first (per your 11.x preference), then Heroic."""
    system = shutil.which("wine")
    if system:
        return Runner(name="system", path=Path(system))
    heroic = sorted(Path("~/.config/heroic/tools/wine").expanduser().glob("*/bin/wine"))
    if heroic:
        return Runner(name="heroic", path=heroic[0])
    return None

class InstallWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(bool, str)
    failed = pyqtSignal(str)

    def __init__(self, runner: Runner, prefix: Path, target: Path,
                 kind: str, is_installer: bool):
        super().__init__()
        self.runner = runner
        self.prefix = prefix
        self.target = target
        self.kind = kind
        self.is_installer = is_installer

    def run(self):
        try:
            if self.is_installer:
                self.progress.emit(f"Running installer {self.target.name} (click through the installer window)...")
                install_from_installer(self.runner, self.prefix, self.target)
            else:
                self.progress.emit(f"Installing {self.target.name} into prefix...")
                install_portable(self.runner, self.prefix, self.target, self.kind)

            found = find_installed_plugins(self.prefix, self.kind)
            self.progress.emit(f"Found in prefix: {[p.name for p in found]}")

            self.progress.emit("Syncing yabridge...")
            add_sync_targets(self.runner, [self.prefix])
            sync_yabridge(self.runner)

            self.done.emit(True, f"Installed {len(found)} plugin(s); yabridge synced.")
        except Exception as exc:  # surfaced to the user, never silently dropped
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            try:
                shutdown_prefix(self.runner, self.prefix)
            except Exception:
                pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_file: Path | None = None
        self.worker: InstallWorker | None = None
        self.setWindowTitle("VST Helper")
        self.setMinimumSize(700, 520)
        self._build_ui()

        # First-run onboarding
        if not FIRST_RUN_FLAG.exists():
            print(f"DEBUG: First run detected, scheduling onboarding")
            QTimer.singleShot(200, self._show_onboarding)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.info_label = QLabel("<h3>Drop or select a plugin file</h3>")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_label)

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse)
        layout.addWidget(browse_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Stats row
        stats_frame = QFrame()
        stats_frame.setStyleSheet("QFrame { background: #2a2a2a; padding: 8px; border-radius: 4px; margin: 10px 0; }")
        stats_layout = QHBoxLayout(stats_frame)

        stats_label = QLabel("📊 Plugins: 0 installed")
        stats_label.setStyleSheet("color: #aaa;")
        stats_layout.addWidget(stats_label)

        stats_layout.addStretch()
        self.stats_label = stats_label
        layout.addWidget(stats_frame)

        self.log_view = QTextEdit(readOnly=True)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.log_view, stretch=1)

        btn_layout = QHBoxLayout()

        self.process_btn = QPushButton("Install")
        self.process_btn.setEnabled(False)
        self.process_btn.clicked.connect(self._process)
        btn_layout.addWidget(self.process_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        btn_layout.addWidget(settings_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.setAcceptDrops(True)

    def _open_settings(self):
        from .settings import SettingsDialog
        dialog = SettingsDialog(self)
        dialog.refresh_triggered.connect(self._refresh_stats)
        dialog.exec()

    def _setup_default_prefix(self):
        """Create default Wine prefix on first run and register it."""
        runner = resolve_runner()
        if runner is None:
            self._log("No Wine found — prefix creation skipped.")
            return

        prefix = DEFAULT_PREFIX

        if prefix.exists() and (prefix / "drive_c").exists():
            self._log(f"Default prefix already exists at {prefix}")
        else:
            if prefix.exists():
                shutil.rmtree(prefix)
            prefix.mkdir(parents=True, exist_ok=True)

            self._log(f"Creating default prefix at {prefix}...")
            try:
                create_prefix(runner, prefix)
                self._log("Default prefix created successfully.")

                # Register prefix in config
                from .config_manager import register_prefix
                register_prefix(str(prefix), runner.name, dxvk_installed=False)
            except Exception as e:
                self._log(f"Failed to create prefix: {e}")

        # Check and register DXVK
        dxvk_exists = (prefix / "drive_c" / "windows" / "system32" / "dxgi.dll").exists()
        if dxvk_exists:
            self._log("DXVK detected in prefix.")
            from .config_manager import update_prefix_dxvk
            update_prefix_dxvk(str(prefix), True)
        else:
            self._log("DXVK not installed. Recommended for better Windows plugin performance.")

    def _refresh_stats(self):
        from .config_manager import get_total_plugin_count
        total = get_total_plugin_count()
        self.stats_label.setText(f"📊 Plugins: {total} installed")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self._load(Path(urls[0].toLocalFile()))

    def _log(self, msg: str):
        self.log_view.append(msg)
        if not FIRST_RUN_FLAG.exists():
            QTimer.singleShot(200, self._show_onboarding)

    def _show_onboarding(self):
        print(f"DEBUG: FIRST_RUN_FLAG={FIRST_RUN_FLAG} exists={FIRST_RUN_FLAG.exists()}")

        dialog = QDialog(self)
        dialog.setWindowTitle("VST Helper — First Run Check")
        dialog.setMinimumWidth(500)
        dialog.resize(600, 450)
        layout = QVBoxLayout(dialog)

        # Header
        title = QLabel("<h2>VST Helper Setup</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Scroll area for health results
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)

        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        results = run_full_health_check()
        icons = {"ok": "✓", "warning": "⚠", "error": "✗", "skipped": "○"}

        for r in results:
            frame = QFrame()
            frame.setStyleSheet("QFrame { padding: 8px; background: #2a2a2a; margin-bottom: 4px; }")
            f_layout = QHBoxLayout(frame)

            icon_label = QLabel(icons.get(r.status.value, "?"))
            icon_label.setStyleSheet("font-size: 14px;")
            f_layout.addWidget(icon_label)

            msg_label = QLabel(r.message)
            msg_label.setWordWrap(True)
            f_layout.addWidget(msg_label, stretch=1)

            results_layout.addWidget(frame)

        # Add "fix needed" note
        needs_fix = any(r.status.value in ("warning", "error") for r in results)
        if needs_fix:
            note = QLabel("\n⚠ Some components need attention. Click 'Auto-Fix' to install missing dependencies.")
            note.setStyleSheet("color: orange; font-weight: bold;")
            note.setWordWrap(True)
            results_layout.addWidget(note)

        scroll.setWidget(results_widget)
        layout.addWidget(scroll)

        # Buttons
        button_layout = QHBoxLayout()

        auto_fix_btn = QPushButton("Auto-Fix Missing Components")
        auto_fix_btn.clicked.connect(lambda: self._auto_fix(dialog, results))

        close_btn = QPushButton("Done")
        close_btn.clicked.connect(dialog.accept)

        button_layout.addWidget(auto_fix_btn)
        button_layout.addStretch()
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

        # Save dialog reference for close
        dialog._fixed = False

        FIRST_RUN_FLAG.parent.mkdir(parents=True, exist_ok=True)
        FIRST_RUN_FLAG.write_text("done\n")

        if dialog.exec() == QDialog.DialogCode.Accepted:
            print("DEBUG: Onboarding completed")

    def _auto_fix(self, dialog, results):
        """Execute package manager commands via pkexec to install missing dependencies."""
        from subprocess import run

        distro = detect_distro()
        warnings = [r for r in results if r.status.value in ("warning", "error")]
        if not warnings:
            QMessageBox.information(self, "Already Fixed", "All components are healthy!")
            return

        dialog._fixed = True

        # Track what we're trying to fix
        fixes_needed = []

        # Check Wine
        wine_status = check_wine()
        if wine_status.status.value != "ok":
            pkg = "wine-staging" if distro == "arch" else "wine"
            fixes_needed.append(("Wine", get_install_command(pkg, distro)))

        # Check yabridge
        ybridge_status = check_yabridge()
        if ybridge_status.status.value != "ok":
            pkg = "yabridge"
            fixes_needed.append(("yabridge", get_install_command(pkg, distro)))

        # Check realtime group
        realtime_status = next((r for r in results if r.component == "Realtime Group"), None)
        if realtime_status and realtime_status.status.value != "ok":
            fixes_needed.append(("Realtime Group", "sudo usermod -aG realtime $USER"))

        # Kernel is informational only - cannot auto-install without reboot
        # So we skip it in auto-fix

        if not fixes_needed:
            QMessageBox.information(self, "Nothing to Fix", "No actions needed.")
            return

        # Show confirmation dialog
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Auto-Fix Setup")
        confirm.setText("Install missing components?")
        confirm.setInformativeText("This will request your password via PolicyKit (pkexec).")
        confirm.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        confirm.setDefaultButton(QMessageBox.StandardButton.Yes)

        if confirm.exec() != QMessageBox.StandardButton.Yes:
            return

        # Execute fixes sequentially
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("Auto-Fix Progress")
        progress_dialog.resize(450, 250)
        p_layout = QVBoxLayout(progress_dialog)

        status_label = QLabel("Starting...")
        status_label.setWordWrap(True)
        p_layout.addWidget(status_label)

        log_text = QTextEdit(readOnly=True)
        log_text.setMinimumHeight(100)
        p_layout.addWidget(log_text)

        cancel_btn = QPushButton("Cancel")
        p_layout.addWidget(cancel_btn)

        cancelled = False
        cancel_btn.clicked.connect(lambda: setattr(progress_dialog, "_cancelled", True))

        for component, cmd in fixes_needed:
            if getattr(progress_dialog, "_cancelled", False):
                status_label.setText("Cancelled.")
                break

            status_label.setText(f"Installing {component}...")
            log_text.append(f"$ {cmd}")

            success, output = run_privileged_command(cmd)
            if success:
                log_text.append(f"✓ {component} installed successfully")
            else:
                log_text.append(f"✗ Failed to install {component}: {output}")

            # Small delay between operations
            QThread.msleep(500)

        # User needs to logout for group membership change
        if any(f[0] == "Realtime Group" for f in fixes_needed):
            log_text.append("\n⚠ Note: Realtime group change requires logout/login.")

        status_label.setText("Auto-fix complete. Restart VST Helper.")
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(progress_dialog.close)
        p_layout.addWidget(close_btn)

        progress_dialog.exec()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Plugin", str(Path.home()),
            "Plugins (*.vst3 *.clap *.lv2 *.exe *.dll);;All Files (*)")
        if path:
            self._load(Path(path))

    def _load(self, path: Path):
        ftype = detect_file_type(path)
        if ftype == FileType.UNKNOWN:
            QMessageBox.warning(self, "Unsupported", f"Cannot classify {path.name}.")
            return
        self.current_file = path
        self.info_label.setText(f"<h3>{path.name}</h3><p>{ftype.value}</p>")
        self._log(f"Loaded {path} as {ftype.value}")
        self.process_btn.setEnabled(True)

    def _process(self):
        if not self.current_file:
            return
        ftype = detect_file_type(self.current_file)

        if ftype in LINUX_TYPES:
            self._install_linux(ftype)
        elif ftype in (FileType.WINDOWS_EXE, FileType.WINDOWS_VST3,
                       FileType.WINDOWS_DLL, FileType.WINDOWS_CLAP,
                       FileType.WINDOWS_RAW):
            self._install_windows(ftype)
        else:
            QMessageBox.warning(self, "Unknown", f"Unhandled type: {ftype.value}")

    def _install_linux(self, ftype: FileType):
        kind = {"linux_vst3": "vst3", "linux_clap": "clap", "linux_lv2": "lv2"}[ftype.value]
        dest_root = USER_DIRS[kind]
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / self.current_file.name
        if dest.exists():
            self._log(f"{dest} already exists — skipping copy.")
            return
        shutil.copytree(self.current_file, dest) if self.current_file.is_dir() \
            else shutil.copy2(self.current_file, dest)
        self._log(f"Copied to {dest}. No yabridge needed for native plugins.")

    def _install_windows(self, ftype: FileType):
        runner = resolve_runner()
        if runner is None:
            QMessageBox.warning(
                self, "Wine required",
                f"This is a Windows plugin ({ftype.value}). Wine is required "
                "to run it, but no Wine installation was found. Install Wine "
                "(system Wine 11.x or a Heroic-managed build) and try again.")
            return

        prefix = DEFAULT_PREFIX

        if prefix.exists():
            if not (prefix / "drive_c").exists():
                self._log(f"Cleaning up invalid prefix at {prefix}...")
                shutil.rmtree(prefix)
            else:
                self._log(f"Using existing prefix at {prefix}")
                kind = "vst3"
                self.worker = InstallWorker(
                    runner, prefix, self.current_file, kind,
                    is_installer=(ftype == FileType.WINDOWS_EXE))
                self.worker.progress.connect(self._log)
                self.worker.done.connect(lambda ok, msg: self._log(f"DONE: {msg}"))
                self.worker.failed.connect(self._log)
                self.worker.start()
                self.process_btn.setEnabled(False)
                self.worker.finished.connect(lambda: self.process_btn.setEnabled(True))
                return

        self._log(f"Creating new prefix at {prefix}...")
        try:
            create_prefix(runner, prefix)
        except Exception as e:
            QMessageBox.critical(
                self, "Prefix Creation Failed",
                f"Failed to create Wine prefix at {prefix}:\n{e}\n\nPlease check your Wine installation and try again.")
            return

        kind = "vst3"
        self.worker = InstallWorker(
            runner, prefix, self.current_file, kind,
            is_installer=(ftype == FileType.WINDOWS_EXE))
        self.worker.progress.connect(self._log)
        self.worker.done.connect(lambda ok, msg: self._log(f"DONE: {msg}"))
        self.worker.failed.connect(self._log)
        self.worker.start()
        self.process_btn.setEnabled(False)
        self.worker.finished.connect(lambda: self.process_btn.setEnabled(True))

def main() -> int:
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")

    app = QApplication(sys.argv[:1])
    app.setApplicationName("VST Helper")
    app.setOrganizationName("MetalMan1245")
    win = MainWindow()
    win.show()
    return app.exec()
