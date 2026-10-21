"""
Database entry point for NOVA.

config.DB_BACKEND decides which engine is used:
    "mysql"  -> mysql_database.MySQLMemoryDB   (recommended, visible in Workbench)
    "sqlite" -> the local fallback below       (no server needed)

If DB_BACKEND is "mysql" but the server is unreachable, NOVA falls back to
SQLite instead of refusing to start, and prints why.
"""

import sqlite3
import threading
from datetime import datetime

from config import DB_BACKEND, DB_FILE


# ======================================================================
#  SQLite fallback - mirrors the MySQL API so the rest of the app is
#  identical no matter which backend is active.
# ======================================================================
class SQLiteMemoryDB:
    backend = "sqlite"

    def __init__(self, path=DB_FILE, conversation_title="NOVA session"):
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self.user_id = self._ensure_user("local", "local@localhost")
        self.conversation_id = self.start_conversation(conversation_title)

    def _create_schema(self):
        c = self.conn
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT 'New conversation',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            memory_type TEXT NOT NULL DEFAULT 'fact',
            content TEXT NOT NULL,
            importance INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tool_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            argument TEXT,
            result TEXT,
            status TEXT NOT NULL DEFAULT 'success',
            created_at TEXT NOT NULL
        );
        """)
        self.conn.commit()

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _ensure_user(self, name, email):
        with self._lock:
            row = self.conn.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if row:
                return row[0]
            cur = self.conn.execute(
                "INSERT INTO users(name, email, created_at) VALUES (?,?,?)",
                (name, email, self._now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def start_conversation(self, title="NOVA session"):
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO conversations(user_id, title, created_at) VALUES (?,?,?)",
                (self.user_id, title, self._now()),
            )
            self.conn.commit()
            self.conversation_id = cur.lastrowid
            return self.conversation_id

    def rename_conversation(self, title):
        with self._lock:
            self.conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, self.conversation_id),
            )
            self.conn.commit()

    def list_conversations(self, limit=20):
        rows = self.conn.execute(
            """SELECT c.id, c.title, c.created_at, COUNT(m.id)
                 FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE c.user_id = ? GROUP BY c.id ORDER BY c.id DESC LIMIT ?""",
            (self.user_id, limit),
        ).fetchall()
        return [
            {"id": r[0], "title": r[1], "created_at": r[2], "message_count": r[3]}
            for r in rows
        ]

    def add_message(self, role, content, conversation_id=None):
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO messages(conversation_id, role, content, created_at) "
                "VALUES (?,?,?,?)",
                (conversation_id or self.conversation_id, role, content, self._now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def recent_messages(self, limit=12, conversation_id=None):
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id or self.conversation_id, limit),
        ).fetchall()
        return list(reversed(rows))

    def search_messages(self, keyword, limit=25):
        rows = self.conn.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        return [
            {"id": r[0], "role": r[1], "content": r[2], "created_at": r[3]} for r in rows
        ]

    def add_memory(self, content, memory_type="fact", importance=5):
        importance = max(1, min(10, int(importance)))
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO memories(user_id, memory_type, content, importance, created_at) "
                "VALUES (?,?,?,?,?)",
                (self.user_id, memory_type, content, importance, self._now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def recent_memories(self, limit=10):
        return [
            r[0]
            for r in self.conn.execute(
                "SELECT content FROM memories WHERE user_id = ? "
                "ORDER BY importance DESC, id DESC LIMIT ?",
                (self.user_id, limit),
            ).fetchall()
        ]

    def memories_detailed(self, limit=20):
        rows = self.conn.execute(
            "SELECT id, memory_type, content, importance, created_at FROM memories "
            "WHERE user_id = ? ORDER BY importance DESC, id DESC LIMIT ?",
            (self.user_id, limit),
        ).fetchall()
        return [
            {
                "id": r[0],
                "memory_type": r[1],
                "content": r[2],
                "importance": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def delete_memory(self, memory_id):
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM memories WHERE id = ? AND user_id = ?",
                (memory_id, self.user_id),
            )
            self.conn.commit()
            return cur.rowcount

    def add_task(self, task_name, status="pending", result=None):
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO tasks(task_name, status, result, created_at) VALUES (?,?,?,?)",
                (task_name, status, result, self._now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def update_task(self, task_id, status, result=None):
        with self._lock:
            self.conn.execute(
                "UPDATE tasks SET status = ?, result = ? WHERE id = ?",
                (status, result, task_id),
            )
            self.conn.commit()

    def recent_tasks(self, limit=20):
        rows = self.conn.execute(
            "SELECT id, task_name, status, result, created_at FROM tasks "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "task_name": r[1],
                "status": r[2],
                "result": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def log_tool(self, tool_name, argument, result, status="success"):
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO tool_logs(tool_name, argument, result, status, created_at) "
                "VALUES (?,?,?,?,?)",
                (tool_name, argument, str(result)[:60000], status, self._now()),
            )
            self.conn.commit()
            return cur.lastrowid

    def recent_tool_logs(self, limit=20):
        rows = self.conn.execute(
            "SELECT id, tool_name, argument, status, created_at FROM tool_logs "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "tool_name": r[1],
                "argument": r[2],
                "status": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def stats(self):
        def count(table):
            return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608
        return {
            "messages": count("messages"),
            "memories": count("memories"),
            "tasks": count("tasks"),
            "tool_logs": count("tool_logs"),
            "conversations": count("conversations"),
        }

    def close(self):
        self.conn.close()


# ======================================================================
#  Backend selection
# ======================================================================
ACTIVE_BACKEND = "sqlite"
BACKEND_MESSAGE = "Using local SQLite database."


def MemoryDB(*args, **kwargs):
    """Factory. Returns a MySQL-backed DB when possible, SQLite otherwise."""
    global ACTIVE_BACKEND, BACKEND_MESSAGE

    if DB_BACKEND.lower() == "mysql":
        try:
            import mysql_config as cfg
            from mysql_database import MySQLMemoryDB

            db = MySQLMemoryDB(*args, **kwargs)
            db.backend = "mysql"
            ACTIVE_BACKEND = "mysql"
            BACKEND_MESSAGE = f"Connected to MySQL at {cfg.safe_summary()}"
            print("[NOVA DB] " + BACKEND_MESSAGE)
            return db
        except Exception as e:
            ACTIVE_BACKEND = "sqlite"
            BACKEND_MESSAGE = (
                f"MySQL unavailable ({e}). Falling back to SQLite: {DB_FILE}. "
                f"Run  python setup_database.py  to fix this."
            )
            print("[NOVA DB] " + BACKEND_MESSAGE)

    db = SQLiteMemoryDB(*args, **kwargs)
    ACTIVE_BACKEND = "sqlite"
    return db
