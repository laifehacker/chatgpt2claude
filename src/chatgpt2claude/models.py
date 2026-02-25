"""Data models for parsed conversations."""

from __future__ import annotations

from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str
    timestamp: float | None = None


class Conversation(BaseModel):
    id: str
    title: str
    create_time: float | None = None
    update_time: float | None = None
    messages: list[Message] = []
    message_count: int = 0
    model_slug: str | None = None


class ConversationChunk(BaseModel):
    conversation_id: str
    conversation_title: str
    chunk_index: int
    text: str
    first_timestamp: float | None = None
    last_timestamp: float | None = None
