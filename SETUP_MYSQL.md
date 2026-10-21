# NOVA 2.0 — MySQL + gemma4:12b setup

## 1. Point NOVA at your MySQL

Open `mysql_config.py` and set your MySQL Workbench root password:

```python
MYSQL_PASSWORD = os.getenv("NOVA_MYSQL_PASSWORD", "root")   # <-- change "root"
```

Nothing else normally needs changing. Defaults are `root@127.0.0.1:3306`, database `nova_ai`.

## 2. Create the database

```powershell
pip install mysql-connector-python
python setup_database.py
```

Or double-click `setup_database.bat`. You should see:

```
Database 'nova_ai' is ready with:
   - conversations
   - memories
   - messages
   - tasks
   - tool_logs
   - users
   - v_chat_history
```

You can also just open `schema.sql` in MySQL Workbench and hit the lightning bolt — same result.

## 3. Run NOVA

```powershell
.\run_nova.bat
```

The footer now reads `NOVA CORE // gemma4:12b // DB: MYSQL`. If it says `DB: SQLITE`, MySQL was unreachable and NOVA fell back to a local file. The reason is printed in the console and shown by the **DATABASE** button.

## 4. Watch it live in Workbench

```sql
USE nova_ai;

SELECT * FROM memories;
SELECT * FROM tool_logs ORDER BY id DESC;
SELECT * FROM v_chat_history;
```

Example after chatting a bit:

```
+----+---------+-------------+--------------------+------------+---------------------+
| id | user_id | memory_type | content            | importance | created_at          |
+----+---------+-------------+--------------------+------------+---------------------+
|  1 |       1 | preference  | User likes Python  |          8 | 2026-09-15 16:42:32 |
|  2 |       1 | fact        | User uses ASUS V16 |          7 | 2026-09-15 16:42:32 |
+----+---------+-------------+--------------------+------------+---------------------+
```

Useful queries:

```sql
-- conversations with message counts
SELECT c.id, c.title, COUNT(m.id) AS messages, c.created_at
FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
GROUP BY c.id ORDER BY c.id DESC;

-- which tools NOVA uses most, and how often they fail
SELECT tool_name,
       COUNT(*) AS runs,
       SUM(status = 'error')   AS errors,
       SUM(status = 'blocked') AS blocked_by_safe_mode
FROM tool_logs GROUP BY tool_name ORDER BY runs DESC;

-- top memories
SELECT content, memory_type, importance FROM memories
ORDER BY importance DESC, id DESC LIMIT 10;
```

## 5. The model

`config.py` now has:

```python
OLLAMA_MODEL = "gemma4:12b"
OLLAMA_AUTO_FALLBACK = True
```

The name must match a **NAME** column value from `ollama list` exactly. If it doesn't, NOVA tries a tag-less match (`gemma4` → `gemma4:12b`) and then falls back to whatever is installed, printing which model it chose. Set `OLLAMA_AUTO_FALLBACK = False` to make a missing model a hard error instead.

## Teaching NOVA memories

The model can now save typed, weighted memories:

```
TOOL: remember | User prefers dark mode | 7 | preference
TOOL: recall | ASUS
TOOL: db_stats
```

`importance` (1–10) and `memory_type` (`fact`, `preference`, `skill`, `event`, `system`) are both optional; they default to `5` and `fact`.

## Troubleshooting

| Symptom                                       | Fix                                                                 |
| --------------------------------------------- | ------------------------------------------------------------------- |
| `Access denied for user 'root'@'localhost'` | Wrong password in`mysql_config.py`.                               |
| `Can't connect to MySQL server`             | Start the`MySQL80` service in `services.msc`.                   |
| `No module named mysql.connector`           | `pip install mysql-connector-python` (not `mysql`).             |
| Footer shows`DB: SQLITE`                    | Read the console line starting`[NOVA DB]` — it says exactly why. |
| Ollama 404 on model                           | Run`ollama list`, copy the NAME into `config.py`.               |
