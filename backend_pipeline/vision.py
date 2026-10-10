"""Independent ECHO Vision entry point (Ctrl+Space).

This module is a separate application from base.py. It owns Ctrl+Space, reuses
ECHO's existing VoiceVisualizer/Faster-Whisper helper and response popup, and
runs cursor capture concurrently with speech transcription.

Run from the project root with:
    python -m backend_pipeline.vision
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Optional

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from backend_pipeline.visual_ollama import VisionResult, process_image_query
from backend_pipeline.response import ResponseWidget
from backend_pipeline.screenshot import (
    CaptureError,
    CaptureResult,
    CursorCaptureSession,
    capture_region_from_samples,
)
from backend_pipeline.visualizer import SAMPLE_RATE, VoiceVisualizer
from backend_pipeline.wisper_ul import transcribe

logger = logging.getLogger("echo.vision")

WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_SPACE = 0x20
VISION_HOTKEY_ID = 0x45435649  # unique ID; separate process from Alt+Space base.py
MAX_LISTENING_MS = 60_000


class CtrlSpaceFilter(QObject, QAbstractNativeEventFilter):
    """Register and receive the Windows global Ctrl+Space hotkey."""

    triggered = Signal()

    def __init__(self) -> None:
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self.registered = False

    def register(self) -> bool:
        if sys.platform != "win32":
            logger.error("The global Ctrl+Space hotkey is currently Windows-only.")
            return False
        self.registered = bool(
            ctypes.windll.user32.RegisterHotKey(
                None,
                VISION_HOTKEY_ID,
                MOD_CONTROL | MOD_NOREPEAT,
                VK_SPACE,
            )
        )
        if not self.registered:
            logger.error(
                "Could not register Ctrl+Space. Another application or a Windows "
                "input-language shortcut may already own this key combination."
            )
        return self.registered

    def unregister(self) -> None:
        if sys.platform == "win32" and self.registered:
            try:
                ctypes.windll.user32.UnregisterHotKey(None, VISION_HOTKEY_ID)
            except Exception:
                logger.exception("Could not unregister Ctrl+Space.")
        self.registered = False

    def nativeEventFilter(self, event_type, message):
        if sys.platform != "win32":
            return False, 0
        if event_type not in ("windows_generic_MSG", "windows_dispatcher_MSG"):
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

        if msg.message == WM_HOTKEY and msg.wParam == VISION_HOTKEY_ID:
            self.triggered.emit()
            return True, 0
        return False, 0


class VisionPipeline(QObject):
    """Coordinate concurrent cursor capture and voice transcription."""

    status_changed = Signal(str)
    _transcript_ready = Signal(int, str)
    _capture_ready = Signal(int, object)
    _analysis_ready = Signal(int, object)
    _worker_failed = Signal(int, str, str)

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.hotkey = CtrlSpaceFilter()
        self.hotkey.triggered.connect(self.activate)
        self._transcript_ready.connect(self._on_transcript_ready)
        self._capture_ready.connect(self._on_capture_ready)
        self._analysis_ready.connect(self._on_analysis_ready)
        self._worker_failed.connect(self._on_worker_failed)

        self.visualizer: Optional[VoiceVisualizer] = None
        self.capture_session: Optional[CursorCaptureSession] = None
        self.response: Optional[ResponseWidget] = None

        self._busy = False
        self._request_id = 0
        self._lock = threading.Lock()
        self._pending_transcript: Optional[str] = None
        self._pending_capture: Optional[CaptureResult] = None
        self._transcript_done = False
        self._capture_done = False
        self._analysis_started = False
        self._listen_timeout: Optional[QTimer] = None

    def start(self) -> bool:
        """Register Ctrl+Space without touching base.py or its Alt+Space hotkey."""
        logger.info("Starting ECHO Vision pipeline (PID=%s, Python=%s).", __import__("os").getpid(), sys.version.split()[0])
        if sys.platform != "win32":
            self.status_changed.emit("Vision global hotkey requires Windows.")
            return False

        self.app.installNativeEventFilter(self.hotkey)
        if not self.hotkey.register():
            self.app.removeNativeEventFilter(self.hotkey)
            self.status_changed.emit(
                "Could not register Ctrl+Space. Check for a key-combination conflict."
            )
            return False

        self.status_changed.emit("Vision ready. Press Ctrl+Space and speak while outlining the target.")
        return True

    @Slot()
    def activate(self) -> None:
        if self._busy:
            self.status_changed.emit("Vision is still handling the previous request.")
            return

        self._busy = True
        self._request_id += 1
        logger.info("========== Vision request #%d started (Ctrl+Space) ==========", self._request_id)
        request_id = self._request_id
        with self._lock:
            self._pending_transcript = None
            self._pending_capture = None
            self._transcript_done = False
            self._capture_done = False
            self._analysis_started = False

        try:
            # Start cursor collection immediately; it runs while the user speaks.
            logger.info("[request %d] Starting cursor-coordinate tracking.", request_id)
            self.capture_session = CursorCaptureSession()
            self.capture_session.start()
            logger.info("[request %d] Cursor-coordinate tracking is active.", request_id)

            # Same floating speech visualizer used by the normal voice pipeline.
            # It emits audio only after speech followed by silence is detected.
            self.visualizer = VoiceVisualizer(auto_start=False)
            self.visualizer.recording_ready.connect(
                lambda audio, rid=request_id: self._on_recording_ready(rid, audio)
            )
            self.visualizer.cancelled.connect(
                lambda rid=request_id: self._on_cancelled(rid)
            )

            logger.info("[request %d] Showing voice visualizer; microphone warm-up is %s ms.", request_id, self.visualizer.MIC_INITIAL_DELAY)
            self.visualizer.show()
            self.visualizer.raise_()
            self.visualizer.activateWindow()
            # Match the existing voice pipeline's microphone warm-up delay.
            QTimer.singleShot(
                self.visualizer.MIC_INITIAL_DELAY,
                self.visualizer.start_listening,
            )

            self._listen_timeout = QTimer(self)
            self._listen_timeout.setSingleShot(True)
            self._listen_timeout.timeout.connect(
                lambda rid=request_id: self._on_listen_timeout(rid)
            )
            self._listen_timeout.start(MAX_LISTENING_MS)
            self.status_changed.emit("Listening and tracking cursor movement...")
        except Exception as exc:
            logger.exception("Could not start ECHO Vision.")
            self._fail_request(request_id, f"Could not start vision input: {exc}")

    @Slot()
    def _on_recording_ready(self, request_id: int, audio) -> None:
        if request_id != self._request_id or not self._busy:
            return
        if self._listen_timeout is not None:
            self._listen_timeout.stop()

        audio_size = getattr(audio, "size", 0)
        logger.info("[request %d] Recording finished; audio samples=%s.", request_id, audio_size)
        if audio_size == 0:
            self._fail_request(request_id, "No audio was captured.")
            return

        # Freeze cursor history now, then process capture and STT concurrently.
        try:
            if self.capture_session is None:
                raise CaptureError("Cursor tracking did not start.")
            points = self.capture_session.stop_and_get_samples()
            self.capture_session = None
            logger.info("[request %d] Cursor tracking stopped; collected %d coordinate samples.", request_id, len(points))
        except Exception as exc:
            self._fail_request(request_id, str(exc))
            return

        self.status_changed.emit("Transcribing speech and preparing screenshot in parallel...")
        logger.info("[request %d] Launching speech transcription and screenshot capture concurrently.", request_id)
        threading.Thread(
            target=self._transcribe_worker,
            args=(request_id, audio),
            name="EchoVisionSTT",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._capture_worker,
            args=(request_id, points),
            name="EchoVisionScreenshot",
            daemon=True,
        ).start()

    def _transcribe_worker(self, request_id: int, audio) -> None:
        started = time.perf_counter()
        logger.info("[request %d] STT started (sample_rate=%s).", request_id, SAMPLE_RATE)
        try:
            transcript = transcribe(audio, SAMPLE_RATE).strip()
            logger.info("[request %d] STT finished in %.2f seconds.", request_id, time.perf_counter() - started)
            if not transcript:
                raise RuntimeError("No speech was recognized. Please try again.")
            self._transcript_ready.emit(request_id, transcript)
        except Exception as exc:
            logger.exception("Vision speech-to-text failed.")
            self._worker_failed.emit(request_id, "Speech recognition", str(exc))

    def _capture_worker(self, request_id: int, points) -> None:
        started = time.perf_counter()
        logger.info("[request %d] Screenshot crop generation started (coordinates=%d).", request_id, len(points))
        try:
            result = capture_region_from_samples(points)
            logger.info("[request %d] Screenshot crop generated in %.2f seconds; bounds=%s, image=%sx%s.", request_id, time.perf_counter() - started, result.bounds, result.image.width, result.image.height)
            self._capture_ready.emit(request_id, result)
        except Exception as exc:
            logger.exception("Vision screenshot capture failed.")
            self._worker_failed.emit(request_id, "Screenshot capture", str(exc))

    @Slot(int, str)
    def _on_transcript_ready(self, request_id: int, transcript: str) -> None:
        if request_id != self._request_id or not self._busy:
            return
        should_start = False
        with self._lock:
            self._pending_transcript = transcript
            self._transcript_done = True
            should_start = self._results_ready_locked()
        logger.info("[request %d] Recognized query: %s", request_id, transcript)
        self.status_changed.emit(f"Recognized query: {transcript}")
        if should_start:
            self._start_analysis(request_id)

    @Slot(int, object)
    def _on_capture_ready(self, request_id: int, capture: CaptureResult) -> None:
        if request_id != self._request_id or not self._busy:
            return
        left, top, right, bottom = capture.bounds
        logger.info(
            "Vision captured %dx%d from %d cursor coordinates.",
            right - left,
            bottom - top,
            capture.coordinate_count,
        )
        should_start = False
        with self._lock:
            self._pending_capture = capture
            self._capture_done = True
            should_start = self._results_ready_locked()
        logger.info("[request %d] Screenshot is ready; cursor samples=%d.", request_id, capture.coordinate_count)
        self.status_changed.emit("Screenshot ready.")
        if should_start:
            self._start_analysis(request_id)

    def _results_ready_locked(self) -> bool:
        if (
            self._transcript_done
            and self._capture_done
            and not self._analysis_started
            and self._pending_transcript
            and self._pending_capture is not None
        ):
            self._analysis_started = True
            return True
        return False

    def _start_analysis(self, request_id: int) -> None:
        with self._lock:
            transcript = self._pending_transcript
            capture = self._pending_capture
        if not transcript or capture is None:
            return
        logger.info("[request %d] Both inputs are ready. Starting image understanding + answer generation.", request_id)
        self.status_changed.emit("Understanding the screenshot and answering your question...")
        threading.Thread(
            target=self._analysis_worker,
            args=(request_id, capture, transcript),
            name="EchoVisionOllama",
            daemon=True,
        ).start()

    def _analysis_worker(self, request_id: int, capture: CaptureResult, transcript: str) -> None:
        started = time.perf_counter()
        logger.info("[request %d] Vision analysis started; image=%sx%s; query=%r.", request_id, capture.image.width, capture.image.height, transcript)
        try:
            result = process_image_query(capture.image, transcript)
            logger.info("[request %d] Vision analysis completed in %.2f seconds.", request_id, time.perf_counter() - started)
            logger.info("[request %d] Visual context: %s", request_id, result.context)
            logger.info("[request %d] Final answer: %s", request_id, result.answer)
            self._analysis_ready.emit(request_id, result)
        except Exception as exc:
            logger.exception("Vision Ollama processing failed.")
            self._worker_failed.emit(request_id, "Ollama vision processing", str(exc))

    @Slot(int, object)
    def _on_analysis_ready(self, request_id: int, result: VisionResult) -> None:
        if request_id != self._request_id or not self._busy:
            return
        self._finish_visualizer()
        if self.response is not None:
            try:
                self.response.close()
            except Exception:
                logger.debug("Could not close previous response window.", exc_info=True)

        logger.info("[request %d] Creating response popup.", request_id)
        self.response = ResponseWidget(result.answer)
        self.response.closed.connect(self._on_response_closed)
        self.response.show()
        self.response.raise_()
        self.response.activateWindow()
        self.response.setFocus()
        logger.info("[request %d] Response popup shown successfully.", request_id)
        self.status_changed.emit("Vision answer ready. Close the popup to run another request.")

    @Slot(int, str, str)
    def _on_worker_failed(self, request_id: int, stage: str, message: str) -> None:
        if request_id != self._request_id or not self._busy:
            return
        self._fail_request(request_id, f"{stage} failed: {message}")

    @Slot()
    def _on_response_closed(self) -> None:
        self.response = None
        self._busy = False
        self.status_changed.emit("Vision ready. Press Ctrl+Space.")

    def _on_cancelled(self, request_id: int) -> None:
        if request_id != self._request_id or not self._busy:
            return
        self._stop_capture_session()
        self._finish_visualizer()
        self._busy = False
        self.status_changed.emit("Vision input cancelled. Press Ctrl+Space to try again.")

    def _on_listen_timeout(self, request_id: int) -> None:
        if request_id != self._request_id or not self._busy:
            return
        self._fail_request(request_id, "Listening timed out. Press Ctrl+Space and speak your question.")

    def _fail_request(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        logger.error("[request %d] REQUEST FAILED: %s", request_id, message)
        self._stop_capture_session()
        self._finish_visualizer()
        if self._listen_timeout is not None:
            self._listen_timeout.stop()
        self._busy = False
        self.status_changed.emit(message)

    def _stop_capture_session(self) -> None:
        session = self.capture_session
        self.capture_session = None
        if session is not None:
            try:
                session.stop_and_get_samples()
            except Exception:
                logger.debug("Cursor tracker cleanup failed.", exc_info=True)

    def _finish_visualizer(self) -> None:
        visualizer = self.visualizer
        self.visualizer = None
        if visualizer is not None:
            try:
                visualizer.finish()
            except Exception:
                logger.debug("Voice visualizer cleanup failed.", exc_info=True)

    def shutdown(self) -> None:
        self.hotkey.unregister()
        try:
            self.app.removeNativeEventFilter(self.hotkey)
        except Exception:
            pass
        self._stop_capture_session()
        self._finish_visualizer()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s.%(msecs)03d [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def main() -> int:
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("ECHO Vision")
    pipeline = VisionPipeline(app)
    pipeline.status_changed.connect(lambda message: logger.info("%s", message))
    app.aboutToQuit.connect(pipeline.shutdown)

    if not pipeline.start():
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
