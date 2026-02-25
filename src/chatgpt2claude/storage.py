"""SQLite storage with FTS5 full-text search."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Conversation


class ConversationStore:
    """SQLite-backed storage for conversations and messages."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                create_time REAL,
                update_time REAL,
                message_count INTEGER,
                model_slug TEXT,
                full_text TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL,
                message_index INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conv
                ON messages(conversation_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
                title,
                full_text,
                content='conversations',
                content_rowid='rowid',
                tokenize='porter unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS conversations_ai
                AFTER INSERT ON conversations BEGIN
                    INSERT INTO conversations_fts(rowid, title, full_text)
                    VALUES (new.rowid, new.title, new.full_text);
                END;

            CREATE TRIGGER IF NOT EXISTS conversations_ad
                AFTER DELETE ON conversations BEGIN
                    INSERT INTO conversations_fts(conversations_fts, rowid, title, full_text)
                    VALUES ('delete', old.rowid, old.title, old.full_text);
                END;

            CREATE TRIGGER IF NOT EXISTS conversations_au
                AFTER UPDATE ON conversations BEGIN
                    INSERT INTO conversations_fts(conversations_fts, rowid, title, full_text)
                    VALUES ('delete', old.rowid, old.title, old.full_text);
                    INSERT INTO conversations_fts(rowid, title, full_text)
                    VALUES (new.rowid, new.title, new.full_text);
                END;

            CREATE TABLE IF NOT EXISTS import_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_time TEXT NOT NULL,
                file_path TEXT,
                conversations_imported INTEGER,
                messages_imported INTEGER
            );
        """)
        self.conn.commit()

    def conversation_exists(self, conversation_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return row is not None

    def upsert_conversation(self, conv: Conversation):
        """Insert or replace a conversation and its messages."""
        full_text = "\n\n".join(
            f"{m.role}: {m.content}" for m in conv.messages
        )

        # Delete existing messages if re-importing
        self.conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv.id,))
        self.conn.execute("DELETE FROM conversations WHERE id = ?", (conv.id,))

        self.conn.execute(
            """INSERT INTO conversations (id, title, create_time, update_time,
               message_count, model_slug, full_text)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conv.id, conv.title, conv.create_time, conv.update_time,
             conv.message_count, conv.model_slug, full_text),
        )

        for idx, msg in enumerate(conv.messages):
            self.conn.execute(
                """INSERT INTO messages (conversation_id, role, content, timestamp, message_index)
                   VALUES (?, ?, ?, ?, ?)""",
                (conv.id, msg.role, msg.content, msg.timestamp, idx),
            )

        self.conn.commit()

    def get_conversation(self, conversation_id: str) -> dict | None:
        """Get a conversation with all its messages."""
        row = self.conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not row:
            return None

        messages = self.conn.execute(
            "SELECT role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY message_index",
            (conversation_id,),
        ).fetchall()

        return {
            "id": row["id"],
            "title": row["title"],
            "create_time": row["create_time"],
            "update_time": row["update_time"],
            "message_count": row["message_count"],
            "model_slug": row["model_slug"],
            "messages": [dict(m) for m in messages],
        }

    def list_conversations(
        self,
        limit: int = 20,
        offset: int = 0,
        keyword: str | None = None,
    ) -> list[dict]:
        """List conversations, optionally filtered by keyword (FTS5)."""
        if keyword:
            rows = self.conn.execute(
                """SELECT c.id, c.title, c.create_time, c.message_count, c.model_slug
                   FROM conversations c
                   JOIN conversations_fts fts ON c.rowid = fts.rowid
                   WHERE conversations_fts MATCH ?
                   ORDER BY c.create_time DESC
                   LIMIT ? OFFSET ?""",
                (keyword, limit, offset),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT id, title, create_time, message_count, model_slug
                   FROM conversations
                   ORDER BY create_time DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()

        return [dict(r) for r in rows]

    def search_keyword(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search using FTS5 MATCH."""
        rows = self.conn.execute(
            """SELECT c.id, c.title, c.create_time, c.message_count,
                      snippet(conversations_fts, 1, '>>>', '<<<', '...', 40) as snippet,
                      rank
               FROM conversations_fts fts
               JOIN conversations c ON c.rowid = fts.rowid
               WHERE conversations_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Get overall database statistics."""
        conv_count = self.conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        msg_count = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

        date_range = self.conn.execute(
            "SELECT MIN(create_time), MAX(create_time) FROM conversations WHERE create_time IS NOT NULL"
        ).fetchone()

        models = self.conn.execute(
            """SELECT model_slug, COUNT(*) as cnt FROM conversations
               WHERE model_slug IS NOT NULL
               GROUP BY model_slug ORDER BY cnt DESC LIMIT 10"""
        ).fetchall()

        return {
            "total_conversations": conv_count,
            "total_messages": msg_count,
            "date_range_start": _format_ts(date_range[0]) if date_range[0] else None,
            "date_range_end": _format_ts(date_range[1]) if date_range[1] else None,
            "top_models": [{"model": r[0], "count": r[1]} for r in models],
            "avg_messages_per_conversation": round(msg_count / conv_count, 1) if conv_count else 0,
        }

    def record_import(self, file_path: str, conversations: int, messages: int):
        self.conn.execute(
            "INSERT INTO import_metadata (import_time, file_path, conversations_imported, messages_imported) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), file_path, conversations, messages),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


def _format_ts(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
