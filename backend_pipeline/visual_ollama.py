"""Local image understanding and query answering for ECHO Vision.

Stage 1: Qwen3-VL creates concise, grounded visual context.
Stage 2: ECHO's existing conversational Ollama model answers the user's
spoken query using that context.
"""

from __future__ import annotations

import io
import logging
import os
import time
from dataclasses import dataclass

import ollama
from PIL import Image

try:
    from backend_pipeline.ollamma import normal_chat
except ImportError:  # Allows launching vision.py from within backend_pipeline.
    from ollamma import normal_chat

logger = logging.getLogger(__name__)

VISION_MODEL = os.getenv("ECHO_VISION_MODEL", "qwen3-vl:4b")
VISION_CONTEXT_TOKENS = int(os.getenv("ECHO_VISION_CONTEXT_TOKENS", "4096"))
VISION_CONTEXT_PREDICT = int(os.getenv("ECHO_VISION_CONTEXT_PREDICT", "220"))

CONTEXT_PROMPT = """
You are ECHO's visual perception module. Inspect the supplied screenshot crop and
write a crisp, factual context summary in no more than 120 words. Prioritize the
main subject/application, readable text and numbers, visible controls, chart or
layout details, and the UI state relevant to a user's question. Do not answer the
user's question yet. Do not guess hidden content, causes, identities, or intent.
Mark illegible text as unclear rather than inventing it. Be concise and grounded.
""".strip()


@dataclass(frozen=True)
class VisionResult:
    context: str
    answer: str
    vision_model: str = VISION_MODEL


def _encode_image(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def describe_image(image: Image.Image) -> str:
    """Generate a concise visual context with the local VLM."""
    if image is None:
        raise ValueError("No screenshot was provided to ECHO's vision model.")

    logger.info(
        "[vision-model] Starting Ollama image request: model=%s, image=%sx%s, context_tokens=%s, max_output_tokens=%s.",
        VISION_MODEL, image.width, image.height, VISION_CONTEXT_TOKENS, VISION_CONTEXT_PREDICT,
    )
    encode_started = time.perf_counter()
    image_bytes = _encode_image(image)
    logger.info(
        "[vision-model] Screenshot encoded as PNG (%s bytes) in %.2f seconds.",
        len(image_bytes), time.perf_counter() - encode_started,
    )
    request_started = time.perf_counter()
    logger.info("[vision-model] Waiting for Ollama response from %s; this can take a while on first load.", VISION_MODEL)
    try:
        response = ollama.chat(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": CONTEXT_PROMPT,
                "images": [image_bytes],
            }],
            options={
                "temperature": 0.1,
                "num_ctx": VISION_CONTEXT_TOKENS,
                "num_predict": VISION_CONTEXT_PREDICT,
            },
        )
    except Exception as exc:
        logger.exception(
            "[vision-model] Ollama image request FAILED after %.2f seconds.",
            time.perf_counter() - request_started,
        )
        raise RuntimeError(
            f"Could not process the screenshot with {VISION_MODEL!r}: {exc}. "
            f"Make sure Ollama is running and run `ollama pull {VISION_MODEL}`."
        ) from exc

    logger.info("[vision-model] Ollama returned a response in %.2f seconds.", time.perf_counter() - request_started)
    context = (response.message.content or "").strip()
    if not context:
        raise RuntimeError(f"Vision model {VISION_MODEL!r} returned an empty context.")

    logger.info("[vision-model] Visual context generated (%d characters): %s", len(context), context)
    return context


def answer_user_query(context: str, user_query: str) -> str:
    """Use ECHO's existing text model to answer from context and query."""
    query = (user_query or "").strip()
    if not query:
        raise ValueError("Speech recognition returned an empty user query.")

    prompt = f"""Answer the user's spoken question using the screenshot context below.
The context is an interpretation of the visible screen and may contain uncertainty.
Do not claim details beyond the evidence. If the screenshot doesn't answer the
question, clearly say what is missing. Be direct, natural, and concise. 

SCREENSHOT CONTEXT:
{context}

USER'S SPOKEN QUESTION:
{query}
""".strip()

    logger.info("[answer-model] Sending spoken query to ECHO's existing conversational model. Query=%r; context_chars=%d.", query, len(context))
    started = time.perf_counter()
    try:
        answer = normal_chat(prompt).strip()
    except Exception:
        logger.exception("[answer-model] Conversational model failed after %.2f seconds.", time.perf_counter() - started)
        raise
    logger.info("[answer-model] Answer returned in %.2f seconds (%d characters).", time.perf_counter() - started, len(answer))
    if not answer:
        raise RuntimeError("ECHO's conversational model returned an empty answer.")
    logger.info("[answer-model] Final answer: %s", answer)
    return answer


def process_image_query(image: Image.Image, user_query: str) -> VisionResult:
    """Understand screenshot, then answer the corresponding spoken question."""
    logger.info("[pipeline] Beginning two-stage visual question answering.")
    started = time.perf_counter()
    context = describe_image(image)
    logger.info("[pipeline] Stage 1/2 complete. Starting spoken-query answer stage.")
    answer = answer_user_query(context, user_query)
    logger.info("[pipeline] Both stages complete in %.2f seconds.", time.perf_counter() - started)
    return VisionResult(context=context, answer=answer)
