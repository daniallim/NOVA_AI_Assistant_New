"""
Creates the nova_ai database and all tables.

Run once:
    python setup_database.py

Safe to re-run: every statement uses IF NOT EXISTS / CREATE OR REPLACE.
"""

import sys
from pathlib import Path

try:
    import mysql.connector
except ImportError:
    print("mysql-connector-python is not installed.")
    print("Run:  pip install mysql-connector-python")
    sys.exit(1)

import mysql_config as cfg

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def split_statements(sql_text):
    """Split on semicolons that end a statement, ignoring ones inside strings."""
    statements, buf, in_str, quote, prev = [], [], False, "", ""
    for ch in sql_text:
        if in_str:
            if ch == quote and prev != "\\":
                in_str = False
            buf.append(ch)
        elif ch in ("'", '"', "`"):
            in_str, quote = True, ch
            buf.append(ch)
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(ch)
        prev = ch
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def strip_comments(sql_text):
    lines = []
    for line in sql_text.splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)


def main():
    if not SCHEMA_PATH.exists():
        print(f"schema.sql not found next to this script ({SCHEMA_PATH}).")
        sys.exit(1)

    print(f"Connecting to MySQL as {cfg.MYSQL_USER}@{cfg.MYSQL_HOST}:{cfg.MYSQL_PORT} ...")
    try:
        conn = mysql.connector.connect(**cfg.connection_kwargs(include_database=False))
    except mysql.connector.Error as e:
        print(f"\nCould not connect: {e}\n")
        print("Checklist:")
        print("  1. Is the MySQL80 service running?  (services.msc)")
        print("  2. Is MYSQL_PASSWORD in mysql_config.py your real root password?")
        print("  3. Is MySQL on port 3306?")
        sys.exit(1)

    cur = conn.cursor()
    sql = strip_comments(SCHEMA_PATH.read_text(encoding="utf-8"))

    created = 0
    for stmt in split_statements(sql):
        try:
            cur.execute(stmt)
            # drain any result set so the next execute() does not error
            try:
                cur.fetchall()
            except mysql.connector.Error:
                pass
            created += 1
        except mysql.connector.Error as e:
            print(f"  ! {e}\n    in: {stmt[:80]}...")
    conn.commit()

    # Seed the default user so the app has something to attach data to.
    cur.execute(f"USE {cfg.MYSQL_DATABASE}")
    cur.execute(
        "INSERT IGNORE INTO users (name, email) VALUES (%s, %s)",
        (cfg.DEFAULT_USER_NAME, cfg.DEFAULT_USER_EMAIL),
    )
    conn.commit()

    cur.execute("SHOW TABLES")
    tables = [r[0] for r in cur.fetchall()]

    cur.close()
    conn.close()

    print(f"\nExecuted {created} statements.")
    print(f"Database '{cfg.MYSQL_DATABASE}' is ready with:")
    for t in tables:
        print(f"   - {t}")
    print("\nOpen MySQL Workbench and run:  USE nova_ai; SELECT * FROM memories;")


if __name__ == "__main__":
    main()
