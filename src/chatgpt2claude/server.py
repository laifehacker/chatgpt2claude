"""FastMCP server with conversation search tools."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from .config import CHROMA_PATH, DATA_DIR, SQLITE_PATH
from .storage import ConversationStore
from .vectorstore import ConversationVectorStore

# Logging to stderr only — stdout is the MCP JSON-RPC transport
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

mcp = FastMCP(
    "chatgpt2claude",
    instructions=(
        "Search and retrieve the user's ChatGPT conversation history. "
        "Use search_conversations to find relevant past discussions by topic. "
        "Use get_conversation to read a full conversation transcript. "
        "Use list_conversations to browse conversations by date or keyword. "
        "Use get_stats for an overview of the imported data."
    ),
)

# Singleton stores — reused across tool calls
_store: ConversationStore | None = None
_vectorstore: ConversationVectorStore | None = None


def _get_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = ConversationStore(SQLITE_PATH)
    return _store


def _get_vectorstore() -> ConversationVectorStore:
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = ConversationVectorStore(CHROMA_PATH)
    return _vectorstore


def _format_ts(ts: float | None) -> str:
    if ts is None:
        return "Unknown date"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _check_data_exists() -> str | None:
    """Return an error message if no data has been imported."""
    if not SQLITE_PATH.exists():
        return (
            "No ChatGPT data found. Please import your data first:\n"
            "  chatgpt2claude import ~/Downloads/your-chatgpt-export.zip"
        )
    return None


@mcp.tool()
def search_conversations(query: str, limit: int = 10) -> str:
    """Search across all ChatGPT conversations using semantic and keyword search.

    Args:
        query: What to search for (natural language)
        limit: Maximum number of results (default 10)
    """
    err = _check_data_exists()
    if err:
        return err

    store = _get_store()
    vectorstore = _get_vectorstore()

    # Semantic search via ChromaDB
    semantic_results = vectorstore.search(query, n_results=limit)

    # Keyword search via SQLite FTS5
    keyword_results = store.search_keyword(query, limit=limit)

    # Merge results: combine both, deduplicate by conversation_id
    scored: dict[str, dict] = {}

    for r in semantic_results:
        scored[r["conversation_id"]] = {
            "conversation_id": r["conversation_id"],
            "title": r["title"],
            "semantic_score": r["score"],
            "keyword_score": 0.0,
            "snippet": r["snippet"],
            "timestamp": r.get("timestamp"),
        }

    for r in keyword_results:
        conv_id = r["id"]
        if conv_id in scored:
            scored[conv_id]["keyword_score"] = 1.0
            if r.get("snippet"):
                scored[conv_id]["keyword_snippet"] = r["snippet"]
        else:
            scored[conv_id] = {
                "conversation_id": conv_id,
                "title": r["title"],
                "semantic_score": 0.0,
                "keyword_score": 1.0,
                "snippet": r.get("snippet", ""),
                "timestamp": r.get("create_time"),
            }

    # Combined score: weighted average
    for data in scored.values():
        data["combined_score"] = 0.7 * data["semantic_score"] + 0.3 * data["keyword_score"]

    ranked = sorted(scored.values(), key=lambda x: x["combined_score"], reverse=True)[:limit]

    if not ranked:
        return f"No conversations found matching '{query}'."

    lines = [f"Found {len(ranked)} conversations matching '{query}':\n"]

    for i, r in enumerate(ranked, 1):
        date = _format_ts(r.get("timestamp"))
        lines.append(f"{i}. **{r['title']}**")
        lines.append(f"   ID: `{r['conversation_id']}`")
        lines.append(f"   Date: {date} | Relevance: {r['combined_score']:.2f}")
        if r.get("snippet"):
            snippet = r["snippet"].replace("\n", " ")[:150]
            lines.append(f"   Preview: {snippet}")
        lines.append("")

    lines.append("Use get_conversation(conversation_id) to read the full transcript.")
    return "\n".join(lines)


@mcp.tool()
def get_conversation(conversation_id: str) -> str:
    """Retrieve a full ChatGPT conversation transcript.

    Args:
        conversation_id: The conversation UUID (from search results)
    """
    err = _check_data_exists()
    if err:
        return err

    store = _get_store()
    conv = store.get_conversation(conversation_id)

    if not conv:
        return f"Conversation not found: {conversation_id}"

    lines = [
        f"# {conv['title']}",
        f"Date: {_format_ts(conv['create_time'])}",
        f"Model: {conv['model_slug'] or 'Unknown'}",
        f"Messages: {conv['message_count']}",
        "",
        "---",
        "",
    ]

    char_count = 0
    max_chars = 50_000

    for msg in conv["messages"]:
        role = "**User**" if msg["role"] == "user" else "**ChatGPT**"
        ts = _format_ts(msg["timestamp"]) if msg["timestamp"] else ""
        header = f"{role}" + (f" ({ts})" if ts else "")
        content = msg["content"]

        remaining_budget = max_chars - char_count
        if remaining_budget <= 0:
            lines.append(
                f"\n... [Truncated — conversation exceeds {max_chars:,} chars. "
                f"Total: {conv['message_count']} messages]"
            )
            break

        lines.append(f"{header}:")

        if len(content) > remaining_budget:
            lines.append(content[:remaining_budget])
            lines.append(
                f"\n... [Truncated — conversation exceeds {max_chars:,} chars. "
                f"Total: {conv['message_count']} messages]"
            )
            break

        char_count += len(content)
        lines.append(content)
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def list_conversations(
    limit: int = 20,
    offset: int = 0,
    keyword: str | None = None,
) -> str:
    """Browse and filter ChatGPT conversations.

    Args:
        limit: Maximum results (default 20)
        offset: Skip this many results (for pagination)
        keyword: Optional keyword to filter by (searches titles and content)
    """
    err = _check_data_exists()
    if err:
        return err

    store = _get_store()
    conversations = store.list_conversations(limit=limit, offset=offset, keyword=keyword)

    if not conversations:
        if keyword:
            return f"No conversations found matching '{keyword}'."
        return "No conversations found."

    lines = []
    if keyword:
        lines.append(f"Conversations matching '{keyword}':\n")
    else:
        lines.append(f"Conversations (showing {offset + 1}–{offset + len(conversations)}):\n")

    for i, c in enumerate(conversations, offset + 1):
        date = _format_ts(c["create_time"])
        model = c["model_slug"] or "?"
        lines.append(f"{i}. **{c['title']}** ({date})")
        lines.append(f"   ID: `{c['id']}` | {c['message_count']} msgs | Model: {model}")

    if len(conversations) == limit:
        lines.append(f"\nMore available — use offset={offset + limit} to see the next page.")

    return "\n".join(lines)


@mcp.tool()
def get_context_summary(conversation_id: str) -> str:
    """Get a quick summary/context of a specific conversation without the full transcript.

    Useful for understanding what a conversation was about before reading the full thing.

    Args:
        conversation_id: The conversation UUID
    """
    err = _check_data_exists()
    if err:
        return err

    store = _get_store()
    conv = store.get_conversation(conversation_id)

    if not conv:
        return f"Conversation not found: {conversation_id}"

    messages = conv["messages"]
    lines = [
        f"# {conv['title']}",
        "",
        f"- **Date**: {_format_ts(conv['create_time'])}",
        f"- **Model**: {conv['model_slug'] or 'Unknown'}",
        f"- **Messages**: {conv['message_count']}",
        "",
    ]

    # Show first 3 exchanges
    lines.append("## Opening:")
    for msg in messages[:6]:
        role = "User" if msg["role"] == "user" else "ChatGPT"
        preview = msg["content"][:200]
        if len(msg["content"]) > 200:
            preview += "..."
        lines.append(f"**{role}**: {preview}")
        lines.append("")

    # Show last 2 exchanges if conversation is long enough
    if len(messages) > 8:
        lines.append("## Most recent:")
        for msg in messages[-4:]:
            role = "User" if msg["role"] == "user" else "ChatGPT"
            preview = msg["content"][:200]
            if len(msg["content"]) > 200:
                preview += "..."
            lines.append(f"**{role}**: {preview}")
            lines.append("")

    return "\n".join(lines)


@mcp.tool()
def get_stats() -> str:
    """Get statistics about the imported ChatGPT conversation history.

    Shows total conversations, messages, date range, and most used models.
    """
    err = _check_data_exists()
    if err:
        return err

    store = _get_store()
    stats = store.get_stats()

    vectorstore = _get_vectorstore()
    chunk_count = vectorstore.count()

    # Calculate storage size
    db_size = SQLITE_PATH.stat().st_size if SQLITE_PATH.exists() else 0
    chroma_size = sum(f.stat().st_size for f in CHROMA_PATH.rglob("*") if f.is_file()) if CHROMA_PATH.exists() else 0
    total_size_mb = (db_size + chroma_size) / (1024 * 1024)

    lines = [
        "# ChatGPT Import Statistics",
        "",
        f"- **Conversations**: {stats['total_conversations']:,}",
        f"- **Messages**: {stats['total_messages']:,}",
        f"- **Avg messages/conversation**: {stats['avg_messages_per_conversation']}",
        f"- **Search index chunks**: {chunk_count:,}",
        f"- **Storage used**: {total_size_mb:.1f} MB",
        "",
    ]

    if stats["date_range_start"]:
        lines.append(f"- **Date range**: {stats['date_range_start']} → {stats['date_range_end']}")
        lines.append("")

    if stats["top_models"]:
        lines.append("## Models used:")
        for m in stats["top_models"]:
            lines.append(f"- {m['model']}: {m['count']:,} conversations")

    lines.append(f"\n*Data stored in: {DATA_DIR}*")
    return "\n".join(lines)
