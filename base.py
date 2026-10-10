"""Echo backend orchestrator.

Voice flow
----------
Alt + Space
    -> show VoiceVisualizer and start microphone capture
    -> Faster-Whisper converts the recording to text
    -> explicit "open/launch/start/run <app>" request: discover and launch locally
    -> otherwise inspect assets/data/user_saved_tasks.txt
    -> compare EVERY saved tag against the transcription

If an app launch is requested:
    -> backend_pipeline/app_launcher.py resolves an installed app and opens it

If a tag is found:
    -> replay assets/databox/session.jsonl with reader.py

If no tag is found:
    -> send the original transcription to Ollama
    -> display the response with response.py

base.py coordinates the existing modules. It delegates app discovery and
launching to app_launcher.py, and microphone capture, speech recognition,
Ollama, session replay, and the response UI to their dedicated modules.
"""

from __future__ import annotations

import ctypes
import json
import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

try:
    from backend_pipeline.app_launcher import extract_open_app_request, launch_application
    from backend_pipeline.ollamma import normal_chat
    from backend_pipeline.reader import replay_session
    from backend_pipeline.response import ResponseWidget
    from backend_pipeline.visualizer import SAMPLE_RATE, VoiceVisualizer
    from backend_pipeline.wisper_ul import transcribe
except ImportError:
    from app_launcher import extract_open_app_request, launch_application
    from ollamma import normal_chat
    from reader import replay_session
    from response import ResponseWidget
    from visualizer import SAMPLE_RATE, VoiceVisualizer
    from wisper_ul import transcribe


logger = logging.getLogger(__name__)


# ============================================================================
# PROJECT PATHS
# ============================================================================

def find_project_root() -> Path:
    """Find the Echo project root.

    base.py normally lives in:
        <project>/backend_pipeline/base.py

    The search also makes the code tolerant of launching base.py from another
    working directory.
    """

    here = Path(__file__).resolve()

    candidates = [
        here.parent,
        here.parent.parent,
        Path.cwd(),
        Path.cwd().parent,
    ]

    for candidate in candidates:
        if (
            (candidate / "assets" / "data" / "user_saved_tasks.txt").is_file()
            or (candidate / "assets" / "data" / "user_saved_task.txt").is_file()
            or (candidate / "assets" / "databox").is_dir()
        ):
            return candidate

    # Normal package layout.
    return here.parent.parent


PROJECT_ROOT = find_project_root()

# The plural filename is the requested/current filename.
TASK_FILE = PROJECT_ROOT / "assets" / "data" / "user_saved_tasks.txt"

# Backward-compatible fallback for the older singular filename.
LEGACY_TASK_FILE = PROJECT_ROOT / "assets" / "data" / "user_saved_task.txt"

# This is deliberately FIXED. A matched tag does not select metadata_loc.
SESSION_FILE = PROJECT_ROOT / "assets" / "databox" / "session.jsonl"


# ============================================================================
# GLOBAL ALT + SPACE
# ============================================================================

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
VK_SPACE = 0x20
HOTKEY_ID = 0x4543484F  # ECHO


class AltSpaceFilter(QObject, QAbstractNativeEventFilter):
    """Receive the Windows global Alt+Space hotkey."""

    triggered = Signal()

    def __init__(self) -> None:
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self.registered = False

    def register(self) -> bool:
        if sys.platform != "win32":
            logger.warning("Global Alt+Space is only implemented for Windows.")
            return False

        user32 = ctypes.windll.user32

        # Do not silently keep an old registration if the backend is restarted
        # inside the same process.
        user32.UnregisterHotKey(None, HOTKEY_ID)

        self.registered = bool(
            user32.RegisterHotKey(
                None,
                HOTKEY_ID,
                MOD_ALT,
                VK_SPACE,
            )
        )

        if not self.registered:
            logger.error(
                "RegisterHotKey(Alt+Space) failed. "
                "Another application may already own the hotkey."
            )

        return self.registered

    def unregister(self) -> None:
        if sys.platform != "win32":
            return

        if self.registered:
            try:
                ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                logger.exception("Could not unregister Alt+Space.")

        self.registered = False

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0

        if event_type not in (
            "windows_generic_MSG",
            "windows_dispatcher_MSG",
        ):
            return False, 0

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", ctypes.c_void_p),
                ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long),
            ]

        try:
            msg = MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0

        if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
            self.triggered.emit()
            return True, 0

        return False, 0


# ============================================================================
# TASK FILE / TAG MATCHING
# ============================================================================

def task_file_path() -> Path | None:
    """Return the available saved-task file."""

    if TASK_FILE.is_file():
        return TASK_FILE

    if LEGACY_TASK_FILE.is_file():
        logger.warning(
            "Using legacy task filename: %s",
            LEGACY_TASK_FILE,
        )
        return LEGACY_TASK_FILE

    logger.error(
        "Saved-task file not found. Expected: %s",
        TASK_FILE,
    )
    return None


def load_saved_tasks() -> list[dict]:
    """Read the saved tasks file.

    The normal format is a JSON array. JSONL and simple key/value blocks are
    also accepted because older Echo task files may use those formats.
    """

    path = task_file_path()
    if path is None:
        return []

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("Could not read %s: %s", path, exc)
        return []

    content = content.strip()
    if not content:
        return []

    # --------------------------------------------------------
    # JSON array / JSON object
    # --------------------------------------------------------
    try:
        parsed = json.loads(content)

        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]

        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # --------------------------------------------------------
    # JSONL
    # --------------------------------------------------------
    tasks: list[dict] = []

    for line in content.splitlines():
        line = line.strip()

        if not line:
            continue

        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(item, dict):
            tasks.append(item)

    if tasks:
        return tasks

    # --------------------------------------------------------
    # Simple text fallback
    # --------------------------------------------------------
    current: dict = {}

    for raw_line in content.splitlines():
        line = raw_line.strip()

        if not line:
            if current:
                tasks.append(current)
                current = {}
            continue

        if ":" not in line and "=" not in line:
            continue

        separator = ":" if ":" in line else "="
        key, value = line.split(separator, 1)

        key = key.strip().lower()
        value = value.strip()

        if key in {"tag", "tags"}:
            current["tags"] = value
        elif key in {"name", "description", "metadata_loc"}:
            current[key] = value

    if current:
        tasks.append(current)

    return tasks


def normalize_for_tag_match(text: str) -> str:
    """Normalize text without changing its words."""

    text = str(text or "").casefold()

    # Make punctuation behave like spaces so:
    # "open, chrome" can still match "open chrome".
    normalized = []
    for char in text:
        normalized.append(char if char.isalnum() or char.isspace() else " ")

    return " ".join("".join(normalized).split())


def get_task_tags(task: dict) -> list[str]:
    """Extract all tags from one saved task."""

    raw_tags = task.get("tags")

    if raw_tags is None:
        raw_tags = task.get("tag")

    if raw_tags is None:
        return []

    if isinstance(raw_tags, list):
        values = raw_tags
    else:
        values = [raw_tags]

    tags: list[str] = []

    for raw_tag in values:
        if not isinstance(raw_tag, str):
            continue

        # Support a task file containing:
        # ["chrome", "browser"]
        # or:
        # "chrome, browser"
        # or:
        # "chrome | browser"
        # or:
        # "chrome; browser"
        pieces = raw_tag.replace("|", ",").replace(";", ",").split(",")

        for piece in pieces:
            tag = piece.strip()
            if tag:
                tags.append(tag)

    return tags


def find_matching_tag(transcription: str) -> str | None:
    """Check EVERY tag of EVERY task against the user transcription.

    This intentionally does not use Ollama, fuzzy matching, similarity
    scoring, metadata_loc, task names, or descriptions.

    A match means the normalized tag occurs in the normalized user text.
    """

    user_text = normalize_for_tag_match(transcription)

    if not user_text:
        return None

    tasks = load_saved_tasks()

    comparison_count = 0

    for task_index, task in enumerate(tasks, start=1):
        tags = get_task_tags(task)

        for tag_index, tag in enumerate(tags, start=1):
            comparison_count += 1

            normalized_tag = normalize_for_tag_match(tag)

            if not normalized_tag:
                continue

            logger.info(
                "[TAG CHECK %d] task=%d tag=%d: %r <-> %r",
                comparison_count,
                task_index,
                tag_index,
                normalized_tag,
                user_text,
            )

            if normalized_tag in user_text:
                logger.info(
                    "[TAG MATCH] Found tag %r in transcription %r",
                    tag,
                    transcription,
                )
                return tag

    logger.info(
        "[TAG MATCH] No tag found after %d comparisons.",
        comparison_count,
    )
    return None


# ============================================================================
# VOICE PIPELINE
# ============================================================================

class PipelineWorker(QObject):
    """Run Whisper, then perform the local tag decision."""

    status = Signal(str)
    transcription_ready = Signal(str)
    task_ready = Signal(str)
    chat_ready = Signal(str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def process(self, audio) -> bool:
        with self._lock:
            if self.running:
                return False

            self._thread = threading.Thread(
                target=self._run,
                args=(audio,),
                name="EchoVoicePipeline",
                daemon=True,
            )
            self._thread.start()
            return True

    def _run(self, audio) -> None:
        try:
            self.status.emit("Converting speech to text...")

            transcription = transcribe(
                audio,
                SAMPLE_RATE,
            ).strip()

            self.transcription_ready.emit(transcription)

            if not transcription:
                self.error.emit("No speech was detected.")
                return

            # ------------------------------------------------------------
            # 1. Explicit app launch request -> launch locally, before task
            # matching or Ollama. User text is never passed to a shell.
            # ------------------------------------------------------------
            requested_app = extract_open_app_request(transcription)
            if requested_app is not None:
                self.status.emit(f"Looking for {requested_app}...")
                result = launch_application(requested_app)
                if result.success:
                    logger.info("Opened application requested by user: %s", result.app_name)
                    self.status.emit(result.message)
                else:
                    logger.warning("Could not open requested application %r: %s", requested_app, result.message)
                    self.status.emit(result.message)
                self.chat_ready.emit(result.message)
                return

            # ------------------------------------------------------------
            # 2. Otherwise, check saved task tags before using Ollama.
            # ------------------------------------------------------------
            self.status.emit("Checking saved task tags...")

            matched_tag = find_matching_tag(transcription)

            if matched_tag is not None:
                self.status.emit(f"Task tag matched: {matched_tag}")
                self.task_ready.emit(matched_tag)
                return

            # ------------------------------------------------------------
            # No tag matched -> normal Ollama only.
            #
            # We deliberately call normal_chat() rather than
            # process_transcription(), because process_transcription()
            # contains the OLD task-detection logic.
            # ------------------------------------------------------------
            self.status.emit("No task tag matched. Asking Ollama...")

            chat = normal_chat(transcription).strip()

            if not chat:
                self.error.emit("Ollama returned an empty response.")
                return

            self.chat_ready.emit(chat)

        except Exception as exc:
            logger.exception("Voice pipeline failed")
            self.error.emit(f"Voice pipeline error: {exc}")


# ============================================================================
# AUTOMATION WORKER
# ============================================================================

class AutomationWorker(QObject):
    """Replay the one fixed session file without blocking Qt."""

    started = Signal(str)
    finished = Signal(str)
    error = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def run(self, session_file: Path) -> bool:
        with self._lock:
            if self.running:
                return False

            self._thread = threading.Thread(
                target=self._run,
                args=(str(session_file),),
                name="EchoAutomation",
                daemon=True,
            )
            self._thread.start()
            return True

    def _run(self, session_file: str) -> None:
        self.started.emit(session_file)

        try:
            replay_session(session_file)
            self.finished.emit(session_file)
        except Exception as exc:
            logger.exception(
                "Automation replay failed: %s",
                session_file,
            )
            self.error.emit(session_file, str(exc))


# ============================================================================
# ECHO BACKEND
# ============================================================================

class EchoBackend(QObject):
    """Coordinate the existing Echo modules."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()

        self.app = app

        self.visualizer: VoiceVisualizer | None = None
        self.pipeline = PipelineWorker()
        self.automation = AutomationWorker()

        self.response: ResponseWidget | None = None

        self.hotkey = AltSpaceFilter()

        self._processing = False
        self._automation_running = False
        self._response_open = False

        # ------------------------------------------------------------
        # Pipeline signals
        # ------------------------------------------------------------
        self.pipeline.status.connect(
            lambda message: emit_event(
                "status",
                message=message,
            )
        )

        self.pipeline.transcription_ready.connect(
            lambda text: emit_event(
                "transcription",
                text=text,
            )
        )

        self.pipeline.task_ready.connect(
            self._on_task_ready
        )

        self.pipeline.chat_ready.connect(
            self._on_chat_ready
        )

        self.pipeline.error.connect(
            self._on_error
        )

        # ------------------------------------------------------------
        # Automation signals
        # ------------------------------------------------------------
        self.automation.started.connect(
            self._on_automation_started
        )

        self.automation.finished.connect(
            self._on_automation_finished
        )

        self.automation.error.connect(
            self._on_automation_error
        )

        # ------------------------------------------------------------
        # Global hotkey
        # ------------------------------------------------------------
        self.hotkey.triggered.connect(
            self._on_alt_space
        )

    # ========================================================================
    # START
    # ========================================================================

    def start(self) -> None:
        """Start Echo in idle mode."""

        self.app.installNativeEventFilter(self.hotkey)

        if sys.platform == "win32":
            if self.hotkey.register():
                emit_event(
                    "status",
                    message="Echo ready. Press Alt+Space.",
                )
            else:
                emit_event(
                    "error",
                    message=(
                        "Could not register Alt+Space. "
                        "Another application may already be using it."
                    ),
                )
        else:
            emit_event(
                "status",
                message=(
                    "Echo ready. Global Alt+Space requires Windows."
                ),
            )

    # ========================================================================
    # NEW LISTENING SESSION
    # ========================================================================

    @Slot()
    def _on_alt_space(self) -> None:
        """Create a fresh visualizer and begin listening."""

        if self._processing:
            emit_event(
                "status",
                message="Echo is still processing the previous request.",
            )
            return

        if self._automation_running:
            emit_event(
                "status",
                message="Automation is still running.",
            )
            return

        self._processing = True

        # VoiceVisualizer.finish() permanently marks the old visualizer as
        # finished. Therefore every Alt+Space request gets a fresh instance.
        self.visualizer = VoiceVisualizer(auto_start=False)

        self.visualizer.recording_started.connect(
            lambda: emit_event("recording_started")
        )
        self.visualizer.recording_ready.connect(
            self._on_recording_ready
        )
        self.visualizer.cancelled.connect(
            self._on_cancelled
        )

        try:
            self.visualizer.show()
            self.visualizer.raise_()
            self.visualizer.activateWindow()

            QTimer.singleShot(
                self.visualizer.MIC_INITIAL_DELAY,
                self.visualizer.start_listening,
            )

            emit_event(
                "hotkey",
                key="Alt+Space",
            )
            emit_event(
                "status",
                message="Listening...",
            )

        except Exception as exc:
            self._on_error(
                f"Could not start voice input: {exc}"
            )

    # ========================================================================
    # RECORDING -> WHISPER
    # ========================================================================

    @Slot(object)
    def _on_recording_ready(self, audio) -> None:
        if not self._processing:
            return

        if getattr(audio, "size", 0) == 0:
            self._on_error("No audio was captured.")
            return

        emit_event(
            "processing_started"
        )

        if not self.pipeline.process(audio):
            self._on_error(
                "Voice pipeline is already busy."
            )

    # ========================================================================
    # MATCHED TAG -> FIXED SESSION
    # ========================================================================

    @Slot(str)
    def _on_task_ready(self, matched_tag: str) -> None:
        """Run /assets/databox/session.jsonl after a tag match."""

        if self.visualizer is not None:
            self.visualizer.finish()

        if not SESSION_FILE.is_file():
            self._on_error(
                f"Session file not found: {SESSION_FILE}"
            )
            return

        emit_event(
            "task",
            tag=matched_tag,
            metadata_loc=str(SESSION_FILE),
        )

        logger.info(
            "Matched tag %r -> executing fixed session: %s",
            matched_tag,
            SESSION_FILE,
        )

        if not self.automation.run(SESSION_FILE):
            self._on_error(
                "Automation worker is already busy."
            )

    # ========================================================================
    # NO TAG -> OLLAMA -> RESPONSE WINDOW
    # ========================================================================

    @Slot(str)
    def _on_chat_ready(self, chat: str) -> None:
        if self.visualizer is not None:
            self.visualizer.finish()

        emit_event(
            "answer",
            text=chat,
        )

        self._show_response(chat)

    def _show_response(self, text: str) -> None:
        if self.response is not None:
            try:
                self.response.close()
            except Exception:
                pass

        self.response = ResponseWidget(text)
        self._response_open = True

        self.response.closed.connect(
            self._on_response_closed
        )

        self.response.show()
        self.response.raise_()
        self.response.activateWindow()
        self.response.setFocus()

    @Slot()
    def _on_response_closed(self) -> None:
        self._response_open = False
        self.response = None
        self._processing = False

        emit_event(
            "status",
            message="Ready. Press Alt+Space.",
        )

    # ========================================================================
    # AUTOMATION CALLBACKS
    # ========================================================================

    @Slot(str)
    def _on_automation_started(self, session_file: str) -> None:
        self._automation_running = True

        emit_event(
            "automation_started",
            metadata_loc=session_file,
        )

        emit_event(
            "status",
            message="Running automation...",
        )

    @Slot(str)
    def _on_automation_finished(self, session_file: str) -> None:
        self._automation_running = False
        self._processing = False

        emit_event(
            "automation_finished",
            metadata_loc=session_file,
        )

        emit_event(
            "status",
            message="Automation finished. Press Alt+Space.",
        )

    @Slot(str, str)
    def _on_automation_error(
        self,
        session_file: str,
        message: str,
    ) -> None:
        self._automation_running = False
        self._processing = False

        emit_event(
            "automation_error",
            metadata_loc=session_file,
            message=message,
        )

        self._on_error(
            f"Automation failed: {message}"
        )

    # ========================================================================
    # ERROR / CANCEL
    # ========================================================================

    @Slot(str)
    def _on_error(self, message: str) -> None:
        logger.error(message)

        emit_event(
            "error",
            message=message,
        )

        if self.visualizer is not None:
            self.visualizer.finish()

        self._processing = False

        emit_event(
            "status",
            message="Ready. Press Alt+Space.",
        )

    @Slot()
    def _on_cancelled(self) -> None:
        self._processing = False

        emit_event(
            "status",
            message="Voice input cancelled. Press Alt+Space.",
        )

    # ========================================================================
    # SHUTDOWN
    # ========================================================================

    def shutdown(self):
        self.hotkey.unregister()

        if self.visualizer is not None:
            try:
                self.visualizer.finish()
            except Exception:
                pass


# ============================================================================
# EVENT OUTPUT
# ============================================================================

def emit_event(event_type: str, **payload) -> None:
    """Write machine-readable launcher events to stdout."""

    message = {
        "type": event_type,
        **payload,
    }

    print(
        "ECHO_EVENT:" + json.dumps(
            message,
            ensure_ascii=False,
        ),
        flush=True,
    )


# ============================================================================
# LOGGING / MAIN
# ============================================================================

def configure_logging() -> None:
    """Keep diagnostics on stderr so stdout stays machine-readable."""

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[%(name)s] %(levelname)s: %(message)s",
    )


def main():
    configure_logging()

    app = QApplication(sys.argv)

    backend = EchoBackend(app)

    app.aboutToQuit.connect(
        backend.shutdown
    )

    backend.start()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
