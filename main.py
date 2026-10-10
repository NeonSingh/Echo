"""
Echo application entry point.

The existing UI structure is preserved. This version adds an asynchronous
voice pipeline:

    Alt+Space
        -> global pynput hotkey
        -> VoiceVisualizer
        -> microphone capture
        -> silence detection
        -> Faster-Whisper transcription
        -> Ollama response

The GUI remains responsive because Whisper and Ollama run outside the Qt
GUI thread.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

from pynput import keyboard

from PySide6.QtCore import Qt, QPoint, QRectF, QEvent, QObject, Signal
from PySide6.QtGui import QFontDatabase, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QWidget, 
    QHBoxLayout,
    QVBoxLayout,
    QSizeGrip,
)

from components.navigation_bar import NavigationBar
from components.main_container import MainContainer

from sections.home import HomeSection
from sections.section_3 import ListSection
from sections.section_2 import NewSection
from sections.section_4 import DocumentsSection
from sections.section_5 import SettingsSection

from styles.theme import RADIUS_WINDOW



class VoiceProcessSignals(QObject):
    """Signals emitted by the standalone base.py voice process."""

    transcription_ready = Signal(str)
    answer_ready = Signal(str)
    error = Signal(str)
    status = Signal(str)
    finished = Signal()


class VoiceProcessManager(QObject):
    """Launch and monitor base.py as a separate process."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.signals = VoiceProcessSignals()
        self.process = None
        self._reader_thread = None
        self._lock = threading.Lock()

        self.base_path = (
            Path(__file__).resolve().parent / "base.py"
        )


    def is_running(self):
        return (
            self.process is not None
            and self.process.poll() is None
        )

    def _build_voice_command(self):
        return "python base.py"

    def start(self):
        with self._lock:
            if self.is_running():
                return False

            if not self.base_path.exists():
                self.signals.error.emit(
                    f"Voice backend not found: {self.base_path}"
                )
                return False

            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            try:
                command = self._build_voice_command()

                print("Starting voice backend...")
                print(f"Working directory: {self.base_path.parent}")
                print(f"Voice command: {command}")

                self.process = subprocess.Popen(
                    command,
                    cwd=str(self.base_path.parent),
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=creationflags,
                )
            except Exception as exc:
                self.process = None
                self.signals.error.emit(
                    f"Could not start voice backend: {exc}"
                )
                return False

            self._reader_thread = threading.Thread(
                target=self._read_output,
                daemon=True,
                name="EchoVoiceProcessReader",
            )
            self._reader_thread.start()

            return True

    def _read_output(self):
        process = self.process

        if process is None or process.stdout is None:
            return

        try:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")

                if not line:
                    continue

                if not line.startswith("ECHO_EVENT:"):
                    print(f"[voice] {line}")
                    continue

                payload = line[len("ECHO_EVENT:"):].strip()

                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    self.signals.error.emit(
                        f"Invalid voice backend event: {line}"
                    )
                    continue

                event_type = event.get("type")

                if event_type == "transcription":
                    self.signals.transcription_ready.emit(
                        event.get("text", "")
                    )

                elif event_type == "answer":
                    self.signals.answer_ready.emit(
                        event.get("text", "")
                    )

                elif event_type == "error":
                    self.signals.error.emit(
                        event.get(
                            "message",
                            "Unknown voice pipeline error.",
                        )
                    )

                elif event_type == "status":
                    self.signals.status.emit(
                        event.get("message", "")
                    )

                elif event_type == "finished":
                    self.signals.finished.emit()

        except Exception as exc:
            self.signals.error.emit(
                f"Voice backend reader error: {exc}"
            )

        finally:
            try:
                process.wait(timeout=2)
            except Exception:
                pass

            self.process = None
            self.signals.finished.emit()

    def stop(self):
        with self._lock:
            process = self.process
            self.process = None

        if process is None:
            return

        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


class VisionProcessManager:
    """Launch backend_pipeline.vision as an independent process."""

    def __init__(self):
        self.process = None
        self.project_dir = Path(__file__).resolve().parent
        self.vision_module = self.project_dir / "backend_pipeline" / "vision.py"

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return True

        if not self.vision_module.exists():
            print(f"Vision backend not found: {self.vision_module}")
            return False

        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            self.process = subprocess.Popen(
                [sys.executable, "-m", "backend_pipeline.vision"],
                cwd=str(self.project_dir),
                creationflags=creationflags,
            )
            print("Started independent ECHO Vision backend (Ctrl + Space).")
            return True
        except Exception as exc:
            self.process = None
            print(f"Could not start vision backend: {exc}")
            return False

    def stop(self):
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return

        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
                process.wait(timeout=2)
            except Exception:
                pass


class VoiceHotkey(QObject):
    """
    Global Alt + Space listener using pynput.

    pynput invokes its keyboard callback from its own background thread.
    The Qt signal safely transfers the event back to the Qt GUI thread.
    """

    triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.listener = None

    def start(self):
        """Start listening for the global Alt + Space hotkey."""

        if self.listener is not None:
            return

        self.listener = keyboard.GlobalHotKeys(
            {
                "<alt>+<space>": self._on_trigger,
            }
        )

        self.listener.start()

        print("Global voice hotkey started: Alt + Space")

    def _on_trigger(self):
        """Emit a Qt signal from the pynput listener thread."""
        self.triggered.emit()

    def stop(self):
        """Stop the global keyboard listener."""

        if self.listener is None:
            return

        try:
            self.listener.stop()
        except Exception:
            pass

        self.listener = None

        print("Global voice hotkey stopped.")


class MainWindow(QWidget):
    """Frameless top-level Echo window."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Echo")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        self.resize(900, 550)
        self.setMinimumSize(750, 450)

        self._drag_pos: QPoint | None = None

        # ============================================================
        # Voice state
        # ============================================================

        self.transcription = ""
        self.ollama_answer = ""
        self.voice_process = VoiceProcessManager(self)

        self.voice_process.signals.transcription_ready.connect(
            self._on_transcription
        )
        self.voice_process.signals.answer_ready.connect(
            self._on_ollama_answer
        )
        self.voice_process.signals.error.connect(
            self._on_voice_error
        )
        self.voice_process.signals.status.connect(
            self._on_voice_status
        )
        self.voice_process.signals.finished.connect(
            self._on_voice_finished
        )

        # ============================================================
        # POSITION CONTROLS
        # ============================================================

        NAV_OFFSET_X = 0
        NAV_OFFSET_Y = 0

        # ============================================================
        # ROOT LAYOUT
        # ============================================================

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)

        root.addLayout(body, stretch=1)

        # ============================================================
        # NAVIGATION BAR
        # ============================================================

        nav_wrapper = QWidget()
        nav_wrapper.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        nav_layout = QVBoxLayout(nav_wrapper)
        nav_layout.setContentsMargins(
            NAV_OFFSET_X,
            NAV_OFFSET_Y,
            0,
            0,
        )
        nav_layout.setSpacing(0)

        self.nav_bar = NavigationBar()
        nav_layout.addWidget(self.nav_bar)

        body.addWidget(nav_wrapper)

        # ============================================================
        # MAIN CONTAINER
        # Window controls are managed by MainContainer.
        # ============================================================

        self.main_container = MainContainer()
        body.addWidget(self.main_container, stretch=1)

        self.main_container.installEventFilter(self)

        # ============================================================
        # RESIZE GRIP
        # ============================================================

        grip_row = QHBoxLayout()
        grip_row.addStretch()

        size_grip = QSizeGrip(self)
        size_grip.setFixedSize(14, 14)
        size_grip.setStyleSheet("background: transparent;")

        grip_row.addWidget(
            size_grip,
            alignment=(
                Qt.AlignmentFlag.AlignBottom
                | Qt.AlignmentFlag.AlignRight
            ),
        )

        root.addLayout(grip_row)

        # ============================================================
        # REGISTER SECTIONS
        # ============================================================

        self.main_container.add_section(HomeSection())
        self.main_container.add_section(NewSection())
        self.main_container.add_section(ListSection())
        self.main_container.add_section(DocumentsSection())
        self.main_container.add_section(SettingsSection())

        # ============================================================
        # NAVIGATION
        # ============================================================

        self.nav_bar.navigate.connect(self._handle_navigation)

    # ================================================================
    # VOICE PIPELINE
    # ================================================================

    def start_voice_input(self):
        """Launch the standalone voice backend process."""

        self.transcription = ""
        self.ollama_answer = ""

        started = self.voice_process.start()

        if started:
            print("Starting Echo voice backend...")

    def _on_transcription(self, text):
        """Store the latest STT result."""
        self.transcription = text

        print("\nYou said:")
        print(self.transcription)

    def _on_ollama_answer(self, answer):
        """Store the latest Ollama response."""
        self.ollama_answer = answer

        print("\nEcho:")
        print(self.ollama_answer)

    def _on_voice_status(self, message):
        if message:
            print(f"[voice] {message}")

    def _on_voice_error(self, message):
        print(message)

    def _on_voice_finished(self):
        print("Voice backend finished.")

    # ================================================================
    # NAVIGATION
    # ================================================================

    def _handle_navigation(self, index):
        """
        Switch sections.

        Whenever the List tab is clicked, re-read user_saved_tasks.txt.
        """

        if index == 2:
            list_section = self.main_container.stack.widget(index)

            if hasattr(list_section, "reload_tasks"):
                list_section.reload_tasks()

        self.main_container.set_current(index)

    # ================================================================
    # DRAGGING: MAIN CONTAINER ONLY
    # ================================================================

    def eventFilter(self, watched, event):
        if watched is self.main_container:

            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    if not self.isMaximized():
                        self._drag_pos = (
                            event.globalPosition().toPoint()
                            - self.frameGeometry().topLeft()
                        )
                    else:
                        self._drag_pos = None

                    return True

            elif event.type() == QEvent.Type.MouseMove:
                if (
                    event.buttons() & Qt.MouseButton.LeftButton
                    and self._drag_pos is not None
                    and not self.isMaximized()
                ):
                    self.move(
                        event.globalPosition().toPoint()
                        - self._drag_pos
                    )
                    return True

            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_pos = None
                return True

            elif event.type() == QEvent.Type.MouseButtonDblClick:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._toggle_maximize()
                    return True

        return super().eventFilter(watched, event)

    # ================================================================
    # WINDOW MAXIMIZE / RESTORE
    # ================================================================

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ================================================================
    # WINDOW SHAPE
    # ================================================================

    def resizeEvent(self, event):
        if self.isMaximized():
            self.clearMask()
        else:
            path = QPainterPath()
            path.addRoundedRect(
                QRectF(self.rect()),
                RADIUS_WINDOW,
                RADIUS_WINDOW,
            )
            self.setMask(
                QRegion(
                    path.toFillPolygon().toPolygon()
                )
            )

        super().resizeEvent(event)

    def paintEvent(self, event):
        # Keep the main window transparent.
        pass


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # ============================================================
    # Load application font
    # ============================================================

    font_path = (
        Path(__file__).resolve().parent
        / "assets"
        / "fonts"
        / "FutureLight-BW15w.ttf"
    )

    font_id = QFontDatabase.addApplicationFont(
        str(font_path)
    )

    if font_id == -1:
        print(
            f"Failed to load font: {font_path}"
        )
    else:
        families = QFontDatabase.applicationFontFamilies(
            font_id
        )

        if families:
            print(
                f"Loaded font: {families[0]}"
            )

    # ============================================================
    # Launch Echo
    # ============================================================

    window = MainWindow()
    window.show()

    # ============================================================
    # Global Alt + Space
    # ============================================================

    voice_hotkey = VoiceHotkey(window)

    voice_hotkey.triggered.connect(
        window.start_voice_input
    )

    voice_hotkey.start()

    # Keep the listener alive for the lifetime of Echo.
    window.voice_hotkey = voice_hotkey

    app.aboutToQuit.connect(
        voice_hotkey.stop
    )

    # Launch Vision separately; it owns Ctrl+Space and does not modify base.py.
    vision_process = VisionProcessManager()
    vision_process.start()
    window.vision_process = vision_process

    try:
        sys.exit(app.exec())
    finally:
        window.voice_process.stop()
        vision_process.stop()


if __name__ == "__main__":
    main()
