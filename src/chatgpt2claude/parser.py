"""Parse ChatGPT export conversations.json tree structure into flat message lists."""

from __future__ import annotations

import logging
from typing import Any

from .models import Conversation, Message

logger = logging.getLogger(__name__)


def _extract_text(parts: list[Any]) -> str:
    """Extract text from message content parts, filtering non-strings."""
    return "\n".join(part for part in parts if isinstance(part, str)).strip()


def _traverse_tree(mapping: dict[str, Any], current_node: str) -> list[str]:
    """Walk from current_node back to root via parent pointers, return node IDs root-first."""
    path: list[str] = []
    visited: set[str] = set()
    node_id = current_node

    while node_id and node_id in mapping:
        if node_id in visited:
            logger.warning("Circular reference detected at node %s", node_id)
            break
        visited.add(node_id)
        path.append(node_id)
        node_id = mapping[node_id].get("parent")

    path.reverse()
    return path


def parse_conversation(conv: dict[str, Any]) -> Conversation | None:
    """Parse a single ChatGPT conversation dict into a Conversation model.

    Returns None if the conversation cannot be parsed.
    """
    conv_id = conv.get("id")
    title = conv.get("title", "Untitled")
    mapping = conv.get("mapping")
    current_node = conv.get("current_node")

    if not conv_id or not mapping:
        logger.warning("Skipping conversation with missing id or mapping")
        return None

    if not current_node or current_node not in mapping:
        logger.warning("Conversation '%s': current_node not found in mapping", title)
        return None

    node_ids = _traverse_tree(mapping, current_node)
    messages: list[Message] = []
    model_slug: str | None = None

    for node_id in node_ids:
        node = mapping[node_id]
        msg_data = node.get("message")
        if msg_data is None:
            continue

        author = msg_data.get("author", {})
        role = author.get("role", "")

        # Skip system messages (unless user-created) and tool messages
        if role == "system":
            metadata = msg_data.get("metadata", {})
            if not metadata.get("is_user_system_message"):
                continue
        if role == "tool":
            continue
        if role not in ("user", "assistant"):
            continue

        content_data = msg_data.get("content", {})
        parts = content_data.get("parts", [])
        text = _extract_text(parts)

        if not text:
            continue

        timestamp = msg_data.get("create_time")

        # Grab model_slug from first assistant message
        if role == "assistant" and model_slug is None:
            model_slug = msg_data.get("metadata", {}).get("model_slug")

        messages.append(Message(role=role, content=text, timestamp=timestamp))

    if not messages:
        logger.debug("Conversation '%s' has no extractable messages, skipping", title)
        return None

    return Conversation(
        id=conv_id,
        title=title,
        create_time=conv.get("create_time"),
        update_time=conv.get("update_time"),
        messages=messages,
        message_count=len(messages),
        model_slug=model_slug,
    )


def parse_conversations(data: list[dict[str, Any]]) -> list[Conversation]:
    """Parse a full conversations.json array into a list of Conversations."""
    conversations: list[Conversation] = []

    for conv_dict in data:
        try:
            conv = parse_conversation(conv_dict)
            if conv is not None:
                conversations.append(conv)
        except Exception:
            title = conv_dict.get("title", "unknown")
            logger.warning("Failed to parse conversation '%s'", title, exc_info=True)

    return conversations
