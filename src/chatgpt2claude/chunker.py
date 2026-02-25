"""Chunk conversations into embeddable segments."""

from __future__ import annotations

from .config import CHUNK_OVERLAP_PAIRS, CHUNK_TURN_PAIRS, MAX_CHUNK_CHARS
from .models import Conversation, ConversationChunk, Message


def _format_turn(user_msg: Message, assistant_msg: Message | None) -> str:
    """Format a single turn pair as text."""
    text = f"User: {user_msg.content}"
    if assistant_msg:
        text += f"\n\nAssistant: {assistant_msg.content}"
    return text


def _group_into_turns(messages: list[Message]) -> list[tuple[Message, Message | None]]:
    """Group messages into (user, assistant) turn pairs.

    Handles orphan messages by pairing user messages with the next assistant message.
    Consecutive assistant messages without a preceding user message are paired as (assistant, None).
    """
    turns: list[tuple[Message, Message | None]] = []
    i = 0

    while i < len(messages):
        msg = messages[i]

        if msg.role == "user":
            # Look ahead for an assistant response
            if i + 1 < len(messages) and messages[i + 1].role == "assistant":
                turns.append((msg, messages[i + 1]))
                i += 2
            else:
                turns.append((msg, None))
                i += 1
        elif msg.role == "assistant":
            # Orphan assistant message — create a synthetic user context
            turns.append((Message(role="user", content="[continued]"), msg))
            i += 1
        else:
            i += 1

    return turns


def chunk_conversation(conversation: Conversation) -> list[ConversationChunk]:
    """Split a conversation into embeddable chunks.

    Returns a list of ConversationChunks including:
    - A title-only chunk (chunk_index=-1) for title-based search
    - Content chunks from sliding window over turn pairs
    """
    chunks: list[ConversationChunk] = []

    # Title chunk for semantic title search
    chunks.append(
        ConversationChunk(
            conversation_id=conversation.id,
            conversation_title=conversation.title,
            chunk_index=-1,
            text=conversation.title,
            first_timestamp=conversation.create_time,
            last_timestamp=conversation.create_time,
        )
    )

    turns = _group_into_turns(conversation.messages)
    if not turns:
        return chunks

    step = max(1, CHUNK_TURN_PAIRS - CHUNK_OVERLAP_PAIRS)

    for chunk_num, window_start in enumerate(range(0, len(turns), step)):
        window_end = min(window_start + CHUNK_TURN_PAIRS, len(turns))
        window = turns[window_start:window_end]

        # Format all turns in the window
        text_parts = [_format_turn(user_msg, asst_msg) for user_msg, asst_msg in window]
        text = "\n\n---\n\n".join(text_parts)

        # Truncate if too long
        if len(text) > MAX_CHUNK_CHARS:
            text = text[:MAX_CHUNK_CHARS] + "..."

        # Gather timestamps
        timestamps = []
        for user_msg, asst_msg in window:
            if user_msg.timestamp is not None:
                timestamps.append(user_msg.timestamp)
            if asst_msg and asst_msg.timestamp is not None:
                timestamps.append(asst_msg.timestamp)

        chunks.append(
            ConversationChunk(
                conversation_id=conversation.id,
                conversation_title=conversation.title,
                chunk_index=chunk_num,
                text=text,
                first_timestamp=min(timestamps) if timestamps else None,
                last_timestamp=max(timestamps) if timestamps else None,
            )
        )

    return chunks
