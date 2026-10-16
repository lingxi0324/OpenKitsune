import sqlite3
import json
import os

# Check workspace ws_1791446309397 (current session's workspace)
db_path = os.path.join('workspaces', 'ws_1791446309397', 'data', 'memory', 'openkitsune.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check conversation_turns table
cursor.execute("SELECT COUNT(*) FROM conversation_turns")
count = cursor.fetchone()[0]
print(f"conversation_turns: {count} rows")

# Check last 10 turns
cursor.execute("SELECT id, session_id, turn_index, role, substr(content, 1, 100) FROM conversation_turns ORDER BY id DESC LIMIT 10")
for row in cursor.fetchall():
    print(f"  id={row[0]}, session={row[1]}, turn={row[2]}, role={row[3]}, content_preview={row[4]}")

# Check memories count
cursor.execute("SELECT COUNT(*) FROM memories")
mem_count = cursor.fetchone()[0]
print(f"memories: {mem_count} rows")

# Check episodes
cursor.execute("SELECT COUNT(*) FROM episodes")
ep_count = cursor.fetchone()[0]
print(f"episodes: {ep_count} rows")

# Check session_tenants
cursor.execute("SELECT * FROM session_tenants")
tenants = cursor.fetchall()
print(f"session_tenants: {len(tenants)} rows")
for t in tenants:
    print(f"  {t}")

conn.close()
