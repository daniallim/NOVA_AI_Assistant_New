"""
MySQL backend for NOVA.

Exposes MySQLMemoryDB, which keeps the same method names the old SQLite
MemoryDB had (add_message / recent_messages / add_memory / recent_memories /
close) so the rest of the app did not need rewriting, and adds the new
conversation, task and tool-log features.
"""

import threading
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling

import mysql_config as cfg

VALID_MEMORY_TYPES = {"fact", "preference", "skill", "event", "system"}
VALID_TASK_STATUS = {"pending", "running", "done", "failed"}
VALID_TOOL_STATUS = {"success", "error", "blocked"}


class MySQLMemoryDB:
    def __init__(self, conversation_title="NOVA session"):
        self._lock = threading.Lock()
        self.pool = pooling.MySQLConnectionPool(
            pool_name="nova_pool",
            pool_size=cfg.MYSQL_POOL_SIZE,
            pool_reset_session=True,
            **cfg.connection_kwargs(include_database=True),
        )
        self.user_id = self._ensure_user(cfg.DEFAULT_USER_NAME, cfg.DEFAULT_USER_EMAIL)
        self.conversation_id = self.start_conversation(conversation_title)

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    @contextmanager
    def _cursor(self, dictionary=False, commit=False):
        conn = self.pool.get_connection()
        cur = conn.cursor(dictionary=dictionary)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()
            conn.close()          # returns the connection to the pool

    # ------------------------------------------------------------------
    # users / conversations
    # ------------------------------------------------------------------
    def _ensure_user(self, name, email):
        with self._cursor(commit=True) as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                "INSERT INTO users (name, email) VALUES (%s, %s)", (name, email)
            )
            return cur.lastrowid

    def start_conversation(self, title="NOVA session"):
        with self._cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO conversations (user_id, title) VALUES (%s, %s)",
                (self.user_id, title[:255]),
            )
            self.conversation_id = cur.lastrowid
            return self.conversation_id

    def rename_conversation(self, title):
        with self._cursor(commit=True) as cur:
            cur.execute(
                "UPDATE conversations SET title = %s WHERE id = %s",
                (title[:255], self.conversation_id),
            )

    def list_conversations(self, limit=20):
        with self._cursor(dictionary=True) as cur:
            cur.execute(
                """SELECT c.id, c.title, c.created_at, COUNT(m.id) AS message_count
                     FROM conversations c
                     LEFT JOIN messages m ON m.conversation_id = c.id
                    WHERE c.user_id = %s
                    GROUP BY c.id, c.title, c.created_at
                    ORDER BY c.id DESC
                    LIMIT %s""",
                (self.user_id, int(limit)),
            )
            return cur.fetchall()

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    def add_message(self, role, content, conversation_id=None):
        if role not in ("user", "assistant", "system", "tool"):
            role = "system"
        with self._cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO messages (conversation_id, role, content) "
                "VALUES (%s, %s, %s)",
                (conversation_id or self.conversation_id, role, content),
            )
            return cur.lastrowid

    def recent_messages(self, limit=12, conversation_id=None):
        """Returns [(role, content), ...] oldest-first, same shape as before."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT role, content FROM messages "
                "WHERE conversation_id = %s ORDER BY id DESC LIMIT %s",
                (conversation_id or self.conversation_id, int(limit)),
            )
            return list(reversed(cur.fetchall()))

    def search_messages(self, keyword, limit=25):
        with self._cursor(dictionary=True) as cur:
            cur.execute(
                """SELECT m.id, m.role, m.content, m.created_at, c.title
                     FROM messages m
                     JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = %s AND m.content LIKE %s
                    ORDER BY m.id DESC LIMIT %s""",
                (self.user_id, f"%{keyword}%", int(limit)),
            )
            return cur.fetchall()

    # ------------------------------------------------------------------
    # memories
    # ------------------------------------------------------------------
    def add_memory(self, content, memory_type="fact", importance=5):
        if memory_type not in VALID_MEMORY_TYPES:
            memory_type = "fact"
        importance = max(1, min(10, int(importance)))
        with self._cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO memories (user_id, memory_type, content, importance) "
                "VALUES (%s, %s, %s, %s)",
                (self.user_id, memory_type, content, importance),
            )
            return cur.lastrowid

    def recent_memories(self, limit=10):
        """Highest-importance memories first. Returns a list of strings."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT content FROM memories WHERE user_id = %s "
                "ORDER BY importance DESC, id DESC LIMIT %s",
                (self.user_id, int(limit)),
            )
            return [r[0] for r in cur.fetchall()]

    def memories_detailed(self, limit=20):
        with self._cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id, memory_type, content, importance, created_at "
                "FROM memories WHERE user_id = %s "
                "ORDER BY importance DESC, id DESC LIMIT %s",
                (self.user_id, int(limit)),
            )
            return cur.fetchall()

    def delete_memory(self, memory_id):
        with self._cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM memories WHERE id = %s AND user_id = %s",
                (int(memory_id), self.user_id),
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    def add_task(self, task_name, status="pending", result=None):
        if status not in VALID_TASK_STATUS:
            status = "pending"
        with self._cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO tasks (task_name, status, result) VALUES (%s, %s, %s)",
                (task_name[:255], status, result),
            )
            return cur.lastrowid

    def update_task(self, task_id, status, result=None):
        if status not in VALID_TASK_STATUS:
            status = "done"
        with self._cursor(commit=True) as cur:
            cur.execute(
                "UPDATE tasks SET status = %s, result = %s WHERE id = %s",
                (status, result, int(task_id)),
            )

    def recent_tasks(self, limit=20):
        with self._cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id, task_name, status, result, created_at "
                "FROM tasks ORDER BY id DESC LIMIT %s",
                (int(limit),),
            )
            return cur.fetchall()

    # ------------------------------------------------------------------
    # tool logs
    # ------------------------------------------------------------------
    def log_tool(self, tool_name, argument, result, status="success"):
        if status not in VALID_TOOL_STATUS:
            status = "success"
        with self._cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO tool_logs (tool_name, argument, result, status) "
                "VALUES (%s, %s, %s, %s)",
                (tool_name[:100], argument, str(result)[:60000], status),
            )
            return cur.lastrowid

    def recent_tool_logs(self, limit=20):
        with self._cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT id, tool_name, argument, status, created_at "
                "FROM tool_logs ORDER BY id DESC LIMIT %s",
                (int(limit),),
            )
            return cur.fetchall()

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------
    def stats(self):
        with self._cursor(dictionary=True) as cur:
            cur.execute(
                """SELECT
                     (SELECT COUNT(*) FROM messages)  AS messages,
                     (SELECT COUNT(*) FROM memories)  AS memories,
                     (SELECT COUNT(*) FROM tasks)     AS tasks,
                     (SELECT COUNT(*) FROM tool_logs) AS tool_logs,
                     (SELECT COUNT(*) FROM conversations) AS conversations"""
            )
            return cur.fetchone()

    def close(self):
        # Pooled connections are returned after every operation; nothing to do.
        pass


def test_connection():
    """Returns (ok: bool, message: str)."""
    try:
        conn = mysql.connector.connect(**cfg.connection_kwargs(include_database=True))
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        version = cur.fetchone()[0]
        cur.close()
        conn.close()
        return True, f"Connected to MySQL {version} ({cfg.safe_summary()})"
    except mysql.connector.Error as e:
        return False, f"MySQL connection failed: {e}"
