"""Reusable Faster-Whisper speech-to-text helper."""

from __future__ import annotations

import logging

import numpy as np
from faster_whisper import WhisperModel


logger = logging.getLogger(__name__)

WHISPER_MODEL_SIZE = "small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
TARGET_SAMPLE_RATE = 16000


class WhisperTranscriber:
    """Lazy-loaded Whisper model reused for the lifetime of the process."""

    def __init__(
        self,
        model_size: str = WHISPER_MODEL_SIZE,
        device: str = WHISPER_DEVICE,
        compute_type: str = WHISPER_COMPUTE_TYPE,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model: WhisperModel | None = None

    def _ensure_model(self) -> WhisperModel:
        if self.model is None:
            logger.info(
                "Loading Whisper (%s) on %s...",
                self.model_size,
                self.device,
            )
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            logger.info("Whisper ready.")

        return self.model

    @staticmethod
    def _resample(
        audio: np.ndarray,
        source_rate: int,
        target_rate: int = TARGET_SAMPLE_RATE,
    ) -> np.ndarray:
        audio = np.asarray(audio, dtype=np.float32).flatten()

        if audio.size == 0 or source_rate == target_rate:
            return audio

        if source_rate <= 0 or target_rate <= 0:
            raise ValueError("Sample rates must be positive.")

        target_length = max(
            1,
            int(round(audio.size * target_rate / source_rate)),
        )

        source_positions = np.linspace(
            0.0,
            1.0,
            num=audio.size,
            endpoint=False,
        )
        target_positions = np.linspace(
            0.0,
            1.0,
            num=target_length,
            endpoint=False,
        )

        return np.interp(
            target_positions,
            source_positions,
            audio,
        ).astype(np.float32)

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int,
    ) -> str:
        model = self._ensure_model()
        prepared_audio = self._resample(
            audio,
            source_rate=sample_rate,
        )

        if prepared_audio.size == 0:
            return ""

        logger.info("Transcribing audio...")

        segments, _info = model.transcribe(
            prepared_audio,
            beam_size=1,
            vad_filter=True,
        )

        return " ".join(
            segment.text.strip()
            for segment in segments
            if segment.text.strip()
        ).strip()


_default_transcriber = WhisperTranscriber()


def transcribe(audio: np.ndarray, sample_rate: int) -> str:
    """Convenience wrapper around the process-local transcriber."""

    return _default_transcriber.transcribe(
        audio,
        sample_rate,
    )
