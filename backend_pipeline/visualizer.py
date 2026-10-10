"""Echo microphone capture and floating voice visualizer."""

from __future__ import annotations

import logging
import threading
import time
import gc

import numpy as np
import sounddevice as sd
from PySide6.QtCore import Qt, QTimer, QPoint, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

WIDTH = 230
HEIGHT = 64
BAR_COUNT = 19

SAMPLE_RATE = 44100
BLOCK_SIZE = 512

BG_COLOR = QColor("#00171D")
BAR_COLOR = QColor("#F5F8F8")
LOADING_COLOR = QColor("#F5F8F8")
TRACK_COLOR = QColor("#29434A")

PILL_MARGIN = 2
PILL_RADIUS = 30

SILENCE_THRESHOLD = 0.008
SILENCE_DURATION = 0.36

BAR_SPACING = 9.5
BAR_MIN_HEIGHT = 3
BAR_MAX_HEIGHT = 30
BAR_WIDTH = 3.3
VISUAL_GAIN = 35.0

LOADING_DURATION = 2.0
BAR_DISAPPEAR_DURATION = 0.5
LOADING_BAR_WIDTH = 180
LOADING_BAR_HEIGHT = 6
LOADING_BAR_RADIUS = 3

# Microphone startup protection.
MIC_START_RETRIES = 12
MIC_START_RETRY_DELAY = 0.20
MIC_INITIAL_DELAY = 300


# ============================================================
# AUDIO INPUT
# ============================================================


class AudioInput:
    """Capture audio while sharing live levels with the visualizer."""

    def __init__(self) -> None:
        self.levels = np.zeros(BAR_COUNT, dtype=np.float32)
        self.rms = 0.0
        self.lock = threading.Lock()
        self.stream = None
        self.chunks: list[np.ndarray] = []
        self.started = False
        self._stream_lock = threading.RLock()

    def callback(self, indata, frames, time_info, status) -> None:
        try:
            if status:
                logger.debug("Audio status: %s", status)

            audio = indata[:, 0].copy()
            if audio.size == 0:
                return

            rms = float(np.sqrt(np.mean(np.square(audio))))

            amplitude = np.abs(audio)
            if len(amplitude) > 1:
                envelope = np.maximum(amplitude, np.roll(amplitude, 1))
                envelope[0] = amplitude[0]
            else:
                envelope = amplitude

            chunks = np.array_split(envelope, BAR_COUNT)
            levels = np.array(
                [
                    np.percentile(chunk, 85) if len(chunk) else 0.0
                    for chunk in chunks
                ],
                dtype=np.float32,
            )

            levels *= VISUAL_GAIN
            levels = np.clip(levels, 0.0, 1.0)

            if rms > 0.003:
                levels = np.maximum(
                    levels,
                    min(0.18, rms * 15.0),
                )

            with self.lock:
                self.chunks.append(audio)
                self.rms = rms
                self.levels = levels

        except Exception:
            # Audio callbacks must never throw into PortAudio.
            logger.exception("Unhandled audio callback error")

    def start(self) -> None:
        """Start a completely fresh PortAudio input stream.

        The explicit stream lock plus full stop/close in ``stop()`` are
        important on Windows, where a just-released device can otherwise
        intermittently reject the next open attempt.
        """
        with self._stream_lock:
            if self.stream is not None and self.started:
                return

            # Never reuse a half-initialized stream object.
            self.stream = None
            self.started = False

        last_error = None

        for attempt in range(1, MIC_START_RETRIES + 1):
            stream = None

            try:
                with self.lock:
                    self.chunks.clear()
                    self.rms = 0.0
                    self.levels.fill(0.0)

                # Resolve the input device for THIS attempt and bind it to
                # the stream. This avoids a default-device race between
                # query_devices() and InputStream().
                device = sd.query_devices(kind="input")
                device_index = device["index"]

                stream = sd.InputStream(
                    device=device_index,
                    samplerate=SAMPLE_RATE,
                    blocksize=BLOCK_SIZE,
                    channels=1,
                    dtype="float32",
                    callback=self.callback,
                )
                stream.start()

                with self._stream_lock:
                    self.stream = stream
                    self.started = True

                # Give Windows/PortAudio a small settling period before the
                # visualizer starts consuming callback data.
                time.sleep(0.05)
                return

            except Exception as exc:
                last_error = exc

                if stream is not None:
                    try:
                        stream.abort()
                    except Exception:
                        try:
                            stream.stop()
                        except Exception:
                            pass

                    try:
                        stream.close()
                    except Exception:
                        pass

                with self._stream_lock:
                    self.stream = None
                    self.started = False

                if attempt < MIC_START_RETRIES:
                    time.sleep(MIC_START_RETRY_DELAY)

        raise RuntimeError(
            f"Could not start microphone after {MIC_START_RETRIES} attempts: "
            f"{last_error}"
        )

    def stop(self) -> None:
        """Fully stop and release the PortAudio stream."""
        with self._stream_lock:
            stream = self.stream
            self.stream = None
            self.started = False

        if stream is None:
            return

        try:
            stream.abort()
        except Exception:
            try:
                stream.stop()
            except Exception:
                pass

        try:
            stream.close()
        except Exception:
            pass

        # Drop our last reference so PortAudio resources are collected before
        # another stream/process tries to claim the device.
        del stream
        gc.collect()
        time.sleep(0.15)

    def get_data(self):
        with self.lock:
            return self.levels.copy(), self.rms

    def get_recording(self) -> np.ndarray:
        with self.lock:
            if not self.chunks:
                return np.empty(0, dtype=np.float32)

            return np.concatenate(self.chunks).astype(
                np.float32,
                copy=False,
            )


# ============================================================
# VISUALIZER WINDOW
# ============================================================


class VoiceVisualizer(QWidget):
    """Floating voice pill with microphone capture and silence detection."""

    recording_started = Signal()
    recording_ready = Signal(object)
    cancelled = Signal()

    # Exposed so base.py does not duplicate timing constants.
    MIC_INITIAL_DELAY = MIC_INITIAL_DELAY

    def __init__(self, auto_start: bool = False) -> None:
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(WIDTH, HEIGHT)

        screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            self.move(
                geometry.x() + (geometry.width() - WIDTH) // 2,
                geometry.y() + geometry.height() - HEIGHT - 8,
            )

        self.audio = AudioInput()
        self.display_levels = np.zeros(BAR_COUNT, dtype=np.float32)
        self.voice_detected = False
        self.last_voice_time = time.monotonic()

        self.loading = False
        self.loading_start_time = 0.0
        self.loading_progress = 0.0
        self.bar_fade = 1.0

        self.drag_position = QPoint()
        self._finished = False
        self._start_attempts = 0
        self._starting = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_visualizer)
        self.timer.start(16)

        if auto_start:
            QTimer.singleShot(MIC_INITIAL_DELAY, self.start_listening)

    # ========================================================
    # LISTENING
    # ========================================================

    def start_listening(self) -> None:
        if (
            self._finished
            or self.loading
            or self._starting
            or self.audio.started
        ):
            return

        self._starting = True
        self._start_attempts += 1

        # Reset per-listen state BEFORE opening the stream.
        self.voice_detected = False
        self.last_voice_time = time.monotonic()
        self.display_levels.fill(0.0)
        self.bar_fade = 1.0
        self.loading = False
        self.loading_progress = 0.0

        try:
            self.audio.start()
            self._start_attempts = 0
            self.recording_started.emit()
            self.update()

        except Exception as exc:
            logger.warning(
                "Microphone startup attempt %d failed: %s",
                self._start_attempts,
                exc,
            )

            if self._start_attempts < 8:
                QTimer.singleShot(
                    max(300, int(MIC_START_RETRY_DELAY * 1000)),
                    self.start_listening,
                )
                return

            logger.exception("Microphone startup failed")
            self.cancelled.emit()

        finally:
            self._starting = False

    def update_visualizer(self) -> None:
        if self._finished:
            return

        if self.loading:
            self._update_loading()
            return

        levels, rms = self.audio.get_data()
        now = time.monotonic()

        if rms > SILENCE_THRESHOLD:
            self.voice_detected = True
            self.last_voice_time = now

        if (
            self.voice_detected
            and now - self.last_voice_time >= SILENCE_DURATION
        ):
            self._begin_processing()
            return

        rising = levels > self.display_levels
        self.display_levels = np.where(
            rising,
            self.display_levels + (levels - self.display_levels) * 0.65,
            self.display_levels + (levels - self.display_levels) * 0.22,
        )
        self.display_levels = np.clip(
            self.display_levels,
            0.0,
            1.0,
        )

        self.update()

    # ========================================================
    # PROCESSING HANDOFF
    # ========================================================

    def _begin_processing(self) -> None:
        if self.loading or self._finished:
            return

        # Stop capture before taking the final immutable waveform snapshot.
        self.audio.stop()
        audio = self.audio.get_recording()

        self.start_loading_animation()
        self.recording_ready.emit(audio)

    def start_loading_animation(self) -> None:
        if self.loading:
            return

        self.loading = True
        self.loading_start_time = time.monotonic()
        self.loading_progress = 0.0
        self.bar_fade = 1.0
        self.update()

    def _update_loading(self) -> None:
        elapsed = time.monotonic() - self.loading_start_time

        self.bar_fade = max(
            0.0,
            1.0 - elapsed / BAR_DISAPPEAR_DURATION,
        )
        self.loading_progress = min(
            1.0,
            elapsed / LOADING_DURATION,
        )

        self.update()

    def finish(self) -> None:
        if self._finished:
            return

        self._finished = True
        self.timer.stop()
        self.audio.stop()
        self.close()

    # ========================================================
    # PAINT
    # ========================================================

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pill = QPainterPath()
        pill.addRoundedRect(
            PILL_MARGIN,
            PILL_MARGIN,
            WIDTH - PILL_MARGIN * 2,
            HEIGHT - PILL_MARGIN * 2,
            PILL_RADIUS,
            PILL_RADIUS,
        )
        painter.fillPath(pill, BG_COLOR)

        if self.bar_fade > 0:
            center_x = WIDTH / 2
            center_y = HEIGHT / 2
            total_width = (BAR_COUNT - 1) * BAR_SPACING
            start_x = center_x - total_width / 2

            bar_color = QColor(BAR_COLOR)
            bar_color.setAlphaF(
                max(0.0, min(1.0, self.bar_fade))
            )
            painter.setBrush(bar_color)
            painter.setPen(Qt.PenStyle.NoPen)

            for i, level in enumerate(self.display_levels):
                bar_height = (
                    BAR_MIN_HEIGHT + level * BAR_MAX_HEIGHT
                ) * self.bar_fade
                bar_height = max(1.0, bar_height)

                x = start_x + i * BAR_SPACING - BAR_WIDTH / 2
                y = center_y - bar_height / 2

                bar_path = QPainterPath()
                bar_path.addRoundedRect(
                    x,
                    y,
                    BAR_WIDTH,
                    bar_height,
                    BAR_WIDTH / 2,
                    BAR_WIDTH / 2,
                )
                painter.fillPath(bar_path, bar_color)

        if self.loading:
            bar_width = LOADING_BAR_WIDTH
            bar_height = LOADING_BAR_HEIGHT
            x = (WIDTH - bar_width) / 2
            y = (HEIGHT - bar_height) / 2

            track = QPainterPath()
            track.addRoundedRect(
                x,
                y,
                bar_width,
                bar_height,
                LOADING_BAR_RADIUS,
                LOADING_BAR_RADIUS,
            )
            painter.fillPath(track, TRACK_COLOR)

            fill_width = bar_width * self.loading_progress
            if fill_width > 0:
                fill = QPainterPath()
                fill.addRoundedRect(
                    x,
                    y,
                    fill_width,
                    bar_height,
                    LOADING_BAR_RADIUS,
                    LOADING_BAR_RADIUS,
                )
                painter.fillPath(fill, LOADING_COLOR)

        painter.end()

    # ========================================================
    # INPUT
    # ========================================================

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(
                event.globalPosition().toPoint()
                - self.drag_position
            )
            event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.finish()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.audio.stop()
        event.accept()


# ============================================================
# STANDALONE ENTRY POINT
# ============================================================


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = QApplication([])
    visualizer = VoiceVisualizer(auto_start=True)
    visualizer.show()
    raise SystemExit(app.exec())
