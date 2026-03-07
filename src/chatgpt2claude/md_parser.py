"""Parse ChatGPT markdown exports (from chatgptexporter) into Conversation models.

Expected markdown format:
    # Title
    Datum: YYYY-MM-DD | Berichten: N
    **User:** message
    ---
    **Assistant:** response
    ---
    ===NEXT===
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from .models import Conversation, Message

logger = logging.getLogger(__name__)


def _generate_id() -> str:
    return str(uuid.uuid4())


def _parse_date(date_str: str) -> float:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").timestamp()
    except ValueError:
        return datetime.now().timestamp()


def parse_markdown_file(text: str) -> list[Conversation]:
    """Parse a markdown file into a list of Conversation objects."""
    raw_convos = re.split(r"\n===NEXT===\n", text)
    conversations: list[Conversation] = []

    for raw_convo in raw_convos:
        raw_convo = raw_convo.strip()
        if not raw_convo:
            continue

        # Extract title
        title_match = re.match(r"^#\s+(.+)", raw_convo)
        title = title_match.group(1).strip() if title_match else "Untitled"

        # Extract date
        date_match = re.search(
            r"Datum:\s*(\d{4}-\d{2}-\d{2})\s*\|\s*Berichten:\s*(\d+)", raw_convo
        )
        create_time = _parse_date(date_match.group(1)) if date_match else datetime.now().timestamp()

        # Find where messages start
        lines = raw_convo.split("\n")
        content_start = 0
        for i, line in enumerate(lines):
            if line.startswith("**User:**") or line.startswith("**Assistant:**"):
                content_start = i
                break
        content = "\n".join(lines[content_start:])

        # Parse messages
        message_pattern = re.compile(
            r"\*\*(User|Assistant)\:\*\*\s*(.*?)(?=\n\*\*(User|Assistant)\:\*\*|\Z)",
            re.DOTALL,
        )

        messages: list[Message] = []
        time_offset = 0

        for match in message_pattern.finditer(content):
            role = match.group(1).lower()
            body = match.group(2).strip()

            # Clean separators
            body = re.sub(r"\n---\s*$", "", body.strip())
            body = re.sub(r"^---\s*\n", "", body.strip())
            body = body.strip()

            if not body:
                continue

            # Skip DALL-E artifacts
            if body.startswith('{"content_type":"image_asset_pointer"'):
                continue
            if "DALL\u00b7E displayed" in body and "The images are already plainly visible" in body:
                continue

            time_offset += 1
            messages.append(
                Message(role=role, content=body, timestamp=create_time + time_offset)
            )

        if not messages:
            continue

        conversations.append(
            Conversation(
                id=_generate_id(),
                title=title,
                create_time=create_time,
                update_time=create_time + time_offset,
                messages=messages,
                message_count=len(messages),
                model_slug=None,
            )
        )

    return conversations


def parse_markdown_path(input_path: Path) -> list[Conversation]:
    """Parse one or more markdown files from a file or directory."""
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = sorted(input_path.glob("*.md"))
    else:
        raise FileNotFoundError(f"Not found: {input_path}")

    all_conversations: list[Conversation] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        convos = parse_markdown_file(text)
        all_conversations.extend(convos)
        logger.info("Parsed %s: %d conversations", f.name, len(convos))

    return all_conversations
