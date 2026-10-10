from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

import ollama


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

OLLAMA_MODEL = "llama3.2:3b"

TASK_MATCH_THRESHOLD = 0.80

APP_DIR = Path(__file__).resolve().parent

TASK_FILE = (
    APP_DIR
    / "assets"
    / "user_saved_task.txt"
)


# ============================================================
# OLLAMA SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are Echo, a friendly AI assistant.

Respond naturally to the user's message.

Use concise conversational English.

Do not decide whether something is an automation task.
Automation task detection is handled by the Python program.

Do not return JSON.
Return only the normal conversational response.
"""


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text: str) -> str:
    """
    Normalize text before comparing task tags.
    """

    text = text.lower().strip()

    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# ECHO COMMAND DETECTION
# ============================================================

def extract_echo_command(text: str) -> str | None:
    """
    Return the command after 'echo'.

    Automation is considered only when the user's speech
    begins with the word 'echo'.

    Examples:

        echo ollama open chrome
        -> ollama open chrome

        Echo open chrome
        -> open chrome

        please echo open chrome
        -> None
    """

    normalized = normalize_text(text)

    if not normalized:
        return None

    words = normalized.split()

    if not words:
        return None

    if words[0] != "echo":
        return None

    command = " ".join(words[1:]).strip()

    return command or None


# ============================================================
# TASK FILE PARSING
# ============================================================

def load_saved_tasks():
    """
    Load saved automation tasks from user_saved_task.txt.

    Expected task information can contain:

        tag
        description
        metadata_loc

    The parser is intentionally tolerant because the task file
    format may contain different separators/formatting.
    """

    if not TASK_FILE.exists():
        return []

    try:
        content = TASK_FILE.read_text(
            encoding="utf-8"
        )
    except Exception:
        return []

    tasks = []

    # --------------------------------------------------------
    # Try JSON first.
    # --------------------------------------------------------

    try:
        parsed = json.loads(content)

        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    tasks.append(item)

        elif isinstance(parsed, dict):
            tasks.append(parsed)

        if tasks:
            return tasks

    except Exception:
        pass

    # --------------------------------------------------------
    # Try JSONL.
    # --------------------------------------------------------

    for line in content.splitlines():

        line = line.strip()

        if not line:
            continue

        try:
            item = json.loads(line)

            if isinstance(item, dict):
                tasks.append(item)

        except Exception:
            continue

    if tasks:
        return tasks

    # --------------------------------------------------------
    # Fallback parser for simple text task definitions.
    #
    # This supports blocks such as:
    #
    # tag: ollama open chrome
    # metadata_loc: assets/databox/...
    #
    # description: ...
    # --------------------------------------------------------

    current = {}

    for raw_line in content.splitlines():

        line = raw_line.strip()

        if not line:

            if current:
                tasks.append(current)
                current = {}

            continue

        match = re.match(
            r"^\s*(tag|tags|description|metadata_loc)"
            r"\s*[:=]\s*(.*?)\s*$",
            line,
            re.IGNORECASE,
        )

        if match:

            key = match.group(1).lower()
            value = match.group(2).strip()

            if key == "tags":
                key = "tag"

            current[key] = value

    if current:
        tasks.append(current)

    return tasks


# ============================================================
# TASK TAG EXTRACTION
# ============================================================

def get_task_tags(task: dict) -> list[str]:
    """
    Extract one or more tags from a task.
    """

    tags = task.get("tag")

    if tags is None:
        tags = task.get("tags")

    if tags is None:
        return []

    if isinstance(tags, list):
        return [
            str(tag).strip()
            for tag in tags
            if str(tag).strip()
        ]

    if isinstance(tags, str):

        # Support:
        #
        # tag: chrome, ollama, browser
        # tag: chrome | ollama
        # tag: chrome; ollama

        parts = re.split(
            r"[,;|]",
            tags,
        )

        return [
            part.strip()
            for part in parts
            if part.strip()
        ]

    return [
        str(tags).strip()
    ]


# ============================================================
# TAG SIMILARITY
# ============================================================

def similarity_score(
    command: str,
    tag: str,
) -> float:
    """
    Return similarity from 0.0 to 1.0.
    """

    command = normalize_text(command)
    tag = normalize_text(tag)

    if not command or not tag:
        return 0.0

    # Exact match.
    if command == tag:
        return 1.0

    # One contains the other.
    if (
        command in tag
        or tag in command
    ):
        shorter = min(
            len(command),
            len(tag),
        )

        longer = max(
            len(command),
            len(tag),
        )

        if longer:
            return shorter / longer

    # Normal sequence similarity.
    sequence_score = SequenceMatcher(
        None,
        command,
        tag,
    ).ratio()

    # Token similarity helps with slightly different
    # word ordering/spacing.
    command_words = set(
        command.split()
    )

    tag_words = set(
        tag.split()
    )

    if command_words and tag_words:

        intersection = (
            command_words
            & tag_words
        )

        union = (
            command_words
            | tag_words
        )

        token_score = (
            len(intersection)
            / len(union)
        )

    else:
        token_score = 0.0

    return max(
        sequence_score,
        token_score,
    )


# ============================================================
# FIND AUTOMATION TASK
# ============================================================

def find_matching_task(command: str):
    """Return the best matching saved task, if it clears the threshold."""

    tasks = load_saved_tasks()

    best_metadata_loc = None
    best_score = 0.0
    best_tag = None
    comparison_count = 0

    logger.info("[ECHO TASK MATCH] Command=%r Threshold=%.0f%%", command, TASK_MATCH_THRESHOLD * 100)

    for task in tasks:
        metadata_loc = task.get("metadata_loc")
        if not metadata_loc:
            continue

        for tag in get_task_tags(task):
            comparison_count += 1
            score = similarity_score(command, tag)

            logger.debug(
                "[COMPARE %02d] %r <-> %r = %.2f%% %s",
                comparison_count,
                command,
                tag,
                score * 100,
                "MATCH" if score >= TASK_MATCH_THRESHOLD else "no match",
            )

            if score > best_score:
                best_score = score
                best_metadata_loc = metadata_loc
                best_tag = tag

    if best_metadata_loc is not None:
        logger.info(
            "[ECHO TASK MATCH] Best tag=%r similarity=%.2f%% metadata_loc=%r",
            best_tag,
            best_score * 100,
            best_metadata_loc,
        )

    if best_metadata_loc is not None and best_score >= TASK_MATCH_THRESHOLD:
        logger.info("[ECHO TASK MATCH] AUTOMATION MATCH")
        return best_metadata_loc, best_score

    logger.info("[ECHO TASK MATCH] NO AUTOMATION MATCH")
    return None, best_score


# ============================================================
# NORMAL OLLAMA CHAT
# ============================================================

def normal_chat(
    transcription: str,
) -> str:
    """
    Send the message to Ollama for normal conversation.
    """

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": transcription,
            },
        ],
        think=False,
    )

    return (
        response.message.content
        .strip()
    )


# ============================================================
# MAIN PROCESSOR
# ============================================================

def process_transcription(
    transcription: str,
) -> dict:
    """
    Main Echo decision pipeline.

    Returns exactly one of:

        {"task": "metadata_loc"}

    or:

        {"chat": "response"}
    """

    transcription = (
        transcription
        or ""
    ).strip()

    if not transcription:
        return {
            "chat": ""
        }

    # --------------------------------------------------------
    # 1. Check for "echo" prefix.
    # --------------------------------------------------------

    command = extract_echo_command(
        transcription
    )

    # --------------------------------------------------------
    # 2. Echo command -> local task matching.
    # --------------------------------------------------------

    if command is not None:

        metadata_loc, score = (
            find_matching_task(
                command
            )
        )

        if metadata_loc:

            return {
                "task": metadata_loc
            }

    # --------------------------------------------------------
    # 3. Everything else -> normal Ollama.
    # --------------------------------------------------------

    response = normal_chat(
        transcription
    )

    return {
        "chat": response
    }


# ============================================================
# COMMAND-LINE TEST
# ============================================================

if __name__ == "__main__":

    import sys

    if len(sys.argv) < 2:

        print(
            "Usage: python ollama.py "
            '"echo open chrome"'
        )

        raise SystemExit(1)

    user_text = " ".join(
        sys.argv[1:]
    )

    result = process_transcription(
        user_text
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
        )
    )