import sqlite3
import json
import os
from datetime import datetime

class MemoryManager:
    """Manages SQLite conversation memory — spec-compliant with domain and metadata support."""

    def __init__(self, db_path="conversations.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # conversations table — spec FR-01, data model §9
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'telegram',
                    domain TEXT NOT NULL DEFAULT 'fpa',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # messages table — spec data model §9
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Auto-migrate: add metadata_json column if it doesn't exist yet
            try:
                conn.execute("ALTER TABLE messages ADD COLUMN metadata_json TEXT")
            except Exception:
                pass  # Column already exists
            conn.commit()

    def _ensure_conversation(self, user_id: str):
        """Ensure a conversation row exists for this user, creating if necessary."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO conversations (user_id, provider, domain) VALUES (?, 'telegram', 'fpa')",
                    (user_id,)
                )
                conn.commit()
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE user_id = ?",
                    (datetime.utcnow().isoformat(), user_id)
                )
                conn.commit()

    def add_message(self, user_id: str, role: str, content: str, metadata: dict = None):
        """Adds a new message to the history, with optional analytical metadata."""
        self._ensure_conversation(user_id)
        meta_str = json.dumps(metadata, ensure_ascii=False) if metadata else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (user_id, role, content, metadata_json) VALUES (?, ?, ?, ?)",
                (user_id, role, content, meta_str)
            )
            conn.commit()

    def get_history(self, user_id: str, limit: int = 30) -> list:
        """Retrieves past messages to recreate the LLM conversation context.
        Limit kept at 30 to avoid prompt explosion (spec FR-06).
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """SELECT role, content, metadata_json FROM (
                    SELECT role, content, metadata_json, timestamp
                    FROM messages WHERE user_id = ?
                    ORDER BY timestamp DESC LIMIT ?
                ) ORDER BY timestamp ASC""",
                (user_id, limit)
            )
            rows = cursor.fetchall()
        result = []
        for row in rows:
            entry = {"role": row[0], "content": row[1]}
            if row[2]:
                try:
                    entry["metadata"] = json.loads(row[2])
                except Exception:
                    pass
            result.append(entry)
        return result

    def clear_history(self, user_id: str):
        """Clears memory for a specific user (both messages and conversation record)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
            conn.commit()
