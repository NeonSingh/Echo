"""
ECHO — Cursor-Aware Region Capture (prototype)

Behavior:
- Tracks cursor coordinates continuously.
- Keeps a rolling 2-second history.
- When the cursor pauses, computes a bounding rectangle containing the
  valid coordinates in that history, expands it by a margin, and captures it.
- Displays a preview; press Esc to close the preview or Ctrl+C in the terminal
  to stop the tracker.

Install:
    pip install pynput mss pillow

Notes:
- This is a capture prototype, not yet connected to Ollama or ECHO's UI.
- The bounds are based on recent cursor coordinates. Fast transit points are
  filtered to reduce accidental giant rectangles, but intentional outlines
  are retained when their points are near the pause-related movement cluster.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import mss
from PIL import Image, ImageDraw
from pynput import mouse


# --------------------------- Configuration ---------------------------

HISTORY_SECONDS = 2.0
SAMPLE_INTERVAL_SECONDS = 0.025  # approximately 40 samples/second
PAUSE_SECONDS = 0.50
PAUSE_RADIUS_PX = 12
CAPTURE_MARGIN_PX = 80

MIN_CAPTURE_WIDTH = 240
MIN_CAPTURE_HEIGHT = 160

# Refuse to capture a region larger than this fraction of the virtual desktop.
MAX_DESKTOP_AREA_FRACTION = 0.70

# If the coordinate bounding box is too large, this prototype rejects it
# instead of silently taking a near-full-screen screenshot.
MAX_CAPTURE_AREA_FRACTION = 0.70

# Preview is enabled so the user can verify the selected region.
SHOW_PREVIEW = True

# Optional: save each accepted capture to this directory.
SAVE_CAPTURES = False
CAPTURE_DIR = "echo_captures"


@dataclass(frozen=True)
class MouseSample:
    timestamp: float
    x: int
    y: int


class CursorRegionCapture:
    def __init__(self) -> None:
        self.samples: Deque[MouseSample] = deque()
        self.lock = threading.Lock()
        self.last_sampled_at = 0.0
        self.last_position: Optional[tuple[int, int]] = None
        self.pause_started_at: Optional[float] = None
        self.pause_anchor: Optional[tuple[int, int]] = None
        self.armed = True
        self.capture_in_progress = False
        self.last_capture_at = 0.0
        self.last_capture_anchor: Optional[tuple[int, int]] = None
        self.stop_event = threading.Event()

        if SAVE_CAPTURES:
            os.makedirs(CAPTURE_DIR, exist_ok=True)

    def on_move(self, x: int, y: int) -> None:
        now = time.monotonic()
        position = (int(x), int(y))

        with self.lock:
            if now - self.last_sampled_at < SAMPLE_INTERVAL_SECONDS:
                # Always keep the current location for pause detection,
                # but sample the history at a bounded rate.
                self.last_position = position
                return

            self.samples.append(MouseSample(now, position[0], position[1]))
            self.last_sampled_at = now
            self.last_position = position

            cutoff = now - HISTORY_SECONDS
            while self.samples and self.samples[0].timestamp < cutoff:
                self.samples.popleft()

            if self.pause_anchor is None:
                self.pause_anchor = position
                self.pause_started_at = now
            else:
                ax, ay = self.pause_anchor
                distance_sq = (position[0] - ax) ** 2 + (position[1] - ay) ** 2
                if distance_sq > PAUSE_RADIUS_PX ** 2:
                    # Movement has resumed; re-arm for the next pause.
                    self.pause_anchor = position
                    self.pause_started_at = now
                    self.armed = True

    def run(self) -> None:
        print("ECHO cursor capture is running.")
        print("Move around the target area, then pause for about 0.5 seconds.")
        print("Press Ctrl+C in this terminal to stop.")
        with mouse.Listener(on_move=self.on_move) as listener:
            try:
                while not self.stop_event.is_set():
                    time.sleep(0.05)
                    self._check_pause_and_capture()
            except KeyboardInterrupt:
                self.stop_event.set()
                listener.stop()
        print("ECHO cursor capture stopped.")

    def _check_pause_and_capture(self) -> None:
        now = time.monotonic()

        with self.lock:
            if self.capture_in_progress or not self.samples or self.last_position is None:
                return

            # A pause is valid only if the latest observed position remains near
            # the current pause anchor for the configured duration.
            if self.pause_started_at is None or self.pause_anchor is None:
                return
            if now - self.pause_started_at < PAUSE_SECONDS:
                return
            if not self.armed:
                return

            # Snapshot the rolling history safely.
            history = list(self.samples)
            anchor = self.pause_anchor
            self.armed = False
            self.capture_in_progress = True

        try:
            bounds = self._calculate_bounds(history, anchor)
            if bounds is None:
                print("ECHO: Not enough reliable cursor points; capture skipped.")
                return

            image = self._capture_bounds(bounds)
            if image is None:
                return

            self.last_capture_at = now
            self.last_capture_anchor = anchor
            print(
                f"ECHO captured region: left={bounds[0]}, top={bounds[1]}, "
                f"width={bounds[2] - bounds[0]}, height={bounds[3] - bounds[1]}"
            )

            if SAVE_CAPTURES:
                filename = os.path.join(
                    CAPTURE_DIR, f"echo_capture_{int(time.time())}.png"
                )
                image.save(filename)
                print(f"Saved: {filename}")

            if SHOW_PREVIEW:
                self._show_preview(image, bounds)
        finally:
            with self.lock:
                self.capture_in_progress = False

    def _calculate_bounds(
        self,
        history: list[MouseSample],
        anchor: tuple[int, int],
    ) -> Optional[tuple[int, int, int, int]]:
        """Return a rectangle containing every valid sample in the 2s window.

        We intentionally do NOT take only the densest cluster: when the user
        traces the boundary of an area, the rectangle must include all points
        along that outline so the content inside it is captured too.
        """
        if len(history) < 4:
            return None

        # Ignore duplicate samples at exactly the same point; retain all other
        # points so an outlined boundary contributes its full extent.
        points = []
        previous = None
        for sample in history:
            point = (sample.x, sample.y)
            if point != previous:
                points.append(point)
                previous = point

        if len(points) < 4:
            return None

        left = min(x for x, _ in points) - CAPTURE_MARGIN_PX
        top = min(y for _, y in points) - CAPTURE_MARGIN_PX
        right = max(x for x, _ in points) + CAPTURE_MARGIN_PX
        bottom = max(y for _, y in points) + CAPTURE_MARGIN_PX

        # Guarantee a minimum useful crop centered on the inferred bounds.
        if right - left < MIN_CAPTURE_WIDTH:
            extra = (MIN_CAPTURE_WIDTH - (right - left)) // 2
            left -= extra
            right += extra
        if bottom - top < MIN_CAPTURE_HEIGHT:
            extra = (MIN_CAPTURE_HEIGHT - (bottom - top)) // 2
            top -= extra
            bottom += extra

        # MSS monitor 0 is the full virtual desktop; it may start at negative
        # coordinates when monitors are arranged left/up of the primary.
        with mss.mss() as sct:
            virtual = sct.monitors[0]
            vleft = virtual["left"]
            vtop = virtual["top"]
            vright = vleft + virtual["width"]
            vbottom = vtop + virtual["height"]

        left = max(left, vleft)
        top = max(top, vtop)
        right = min(right, vright)
        bottom = min(bottom, vbottom)

        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            return None

        desktop_area = virtual["width"] * virtual["height"]
        if width * height > desktop_area * MAX_CAPTURE_AREA_FRACTION:
            print(
                "ECHO: Recent cursor points span too much of the desktop; "
                "capture skipped. Move around the target area, then pause."
            )
            return None

        return int(left), int(top), int(right), int(bottom)

    def _capture_bounds(
        self, bounds: tuple[int, int, int, int]
    ) -> Optional[Image.Image]:
        left, top, right, bottom = bounds
        region = {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }

        try:
            with mss.mss() as sct:
                shot = sct.grab(region)
                return Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception as exc:
            print(f"ECHO: Screen capture failed: {exc}")
            return None

    def _show_preview(
        self, image: Image.Image, bounds: tuple[int, int, int, int]
    ) -> None:
        # Add a small title strip so the preview identifies the inferred bounds.
        preview = image.copy()
        draw = ImageDraw.Draw(preview)
        label = (
            f"ECHO capture | {bounds[2] - bounds[0]}x{bounds[3] - bounds[1]} "
            f"| press any key to close"
        )
        draw.rectangle((0, 0, preview.width, 28), fill="black")
        draw.text((8, 7), label, fill="white")

        try:
            preview.show(title="ECHO Capture Preview")
        except Exception as exc:
            print(f"ECHO: Could not open preview: {exc}")


if __name__ == "__main__":
    CursorRegionCapture().run()
