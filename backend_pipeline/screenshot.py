"""Cursor-coordinate tracking and screenshot-region capture for ECHO Vision.

The tracker starts when the Vision hotkey activates and stops when the speech
visualizer completes recording. The captured rectangle encloses every valid
sampled cursor coordinate from that interval, expanded by a configurable margin.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Iterable

import mss
from PIL import Image
from pynput import mouse

logger = logging.getLogger(__name__)

DEFAULT_MARGIN_PX = 80
MIN_CAPTURE_WIDTH = 240
MIN_CAPTURE_HEIGHT = 160
MAX_CAPTURE_AREA_FRACTION = 0.80


@dataclass(frozen=True)
class CursorSample:
    timestamp: float
    x: int
    y: int


@dataclass(frozen=True)
class CaptureResult:
    image: Image.Image
    bounds: tuple[int, int, int, int]  # left, top, right, bottom (right/bottom exclusive)
    coordinate_count: int


class CaptureError(RuntimeError):
    """Base error for cursor-driven screenshot capture."""


class RegionTooLargeError(CaptureError):
    """Raised when cursor movement implies an unsafe/ambiguous large region."""


class CursorCaptureSession:
    """Record cursor coordinates until ``stop_and_get_samples`` is called.

    This intentionally does not wait for a pause. In the voice-triggered flow,
    tracking spans the spoken query so a traced outline is kept in full.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: list[CursorSample] = []
        self._listener: mouse.Listener | None = None
        self._started = False
        self._stopped = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._started and not self._stopped

    def start(self) -> None:
        """Start tracking and seed history with the current pointer position."""
        with self._lock:
            if self._started and not self._stopped:
                return
            self._samples = []
            self._stopped = False
            self._started = True

        try:
            x, y = mouse.Controller().position
            self._record(int(x), int(y))
            listener = mouse.Listener(on_move=self._on_move)
            listener.start()
            with self._lock:
                self._listener = listener
            logger.debug("Cursor-coordinate capture started.")
        except Exception as exc:
            with self._lock:
                self._stopped = True
                self._started = False
            raise CaptureError(f"Could not start cursor tracking: {exc}") from exc

    def _on_move(self, x: int, y: int) -> None:
        self._record(int(x), int(y))

    def _record(self, x: int, y: int) -> None:
        sample = CursorSample(time.monotonic(), x, y)
        with self._lock:
            if self._stopped:
                return
            # Keep every callback coordinate; do not down-sample the outline's
            # turning points, which define the bounding rectangle.
            self._samples.append(sample)

    def stop_and_get_samples(self) -> list[CursorSample]:
        """Stop the listener and return an immutable snapshot of the path."""
        with self._lock:
            if self._stopped:
                return list(self._samples)
            self._stopped = True
            listener = self._listener
            self._listener = None

        if listener is not None:
            try:
                listener.stop()
                listener.join(timeout=1.0)
            except Exception:
                logger.debug("Cursor listener shutdown raised.", exc_info=True)

        # Include the final pointer location as a final valid sample.
        try:
            x, y = mouse.Controller().position
            with self._lock:
                self._samples.append(CursorSample(time.monotonic(), int(x), int(y)))
        except Exception:
            logger.debug("Could not sample final pointer position.", exc_info=True)

        with self._lock:
            samples = list(self._samples)
            self._started = False

        if not samples:
            raise CaptureError("No cursor coordinates were recorded during the request.")
        return samples


def capture_region_from_samples(
    samples: Iterable[CursorSample],
    margin_px: int = DEFAULT_MARGIN_PX,
) -> CaptureResult:
    """Capture the rectangle enclosing all valid samples plus ``margin_px``."""
    points = list(samples)
    if not points:
        raise CaptureError("No cursor coordinates were supplied for capture.")
    if margin_px < 0:
        raise ValueError("margin_px must be zero or greater.")

    try:
        with mss.mss() as sct:
            desktop = sct.monitors[0]  # virtual desktop, including monitor offsets
            d_left = int(desktop["left"])
            d_top = int(desktop["top"])
            d_right = d_left + int(desktop["width"])
            d_bottom = d_top + int(desktop["height"])

            valid = [
                point for point in points
                if d_left <= point.x < d_right and d_top <= point.y < d_bottom
            ]
            if not valid:
                raise CaptureError(
                    "Recorded cursor coordinates do not overlap the virtual desktop. "
                    "Check Windows display scaling or multi-monitor configuration."
                )

            # This rectangle contains every valid point from the tracking
            # interval, so tracing the outer boundary captures its interior.
            left = min(p.x for p in valid) - margin_px
            top = min(p.y for p in valid) - margin_px
            right = max(p.x for p in valid) + margin_px + 1
            bottom = max(p.y for p in valid) + margin_px + 1

            # A stationary hover still needs useful contextual pixels.
            if right - left < MIN_CAPTURE_WIDTH:
                extra = (MIN_CAPTURE_WIDTH - (right - left) + 1) // 2
                left -= extra
                right += extra
            if bottom - top < MIN_CAPTURE_HEIGHT:
                extra = (MIN_CAPTURE_HEIGHT - (bottom - top) + 1) // 2
                top -= extra
                bottom += extra

            # Clamp to the virtual desktop bounds (also handles negative origins).
            left = max(d_left, left)
            top = max(d_top, top)
            right = min(d_right, right)
            bottom = min(d_bottom, bottom)

            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                raise CaptureError("The inferred screenshot region is empty.")

            desktop_area = int(desktop["width"]) * int(desktop["height"])
            if width * height > desktop_area * MAX_CAPTURE_AREA_FRACTION:
                raise RegionTooLargeError(
                    "The cursor path encloses most of the desktop, so the target is "
                    "ambiguous. Trace the intended region more locally and try again."
                )

            region = {
                "left": int(left),
                "top": int(top),
                "width": int(width),
                "height": int(height),
            }
            shot = sct.grab(region)
            image = Image.frombytes("RGB", shot.size, shot.rgb)

    except CaptureError:
        raise
    except Exception as exc:
        raise CaptureError(f"Screen-region capture failed: {exc}") from exc

    bounds = (int(left), int(top), int(right), int(bottom))
    logger.info(
        "Captured region %dx%d from %d valid cursor coordinates (margin=%dpx).",
        width,
        height,
        len(valid),
        margin_px,
    )
    return CaptureResult(image=image, bounds=bounds, coordinate_count=len(valid))
