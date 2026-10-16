import sqlite3
db_path = 'data/memory/openkitsune.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('tables:', tables)
for t in tables:
    tname = t[0]
    cursor.execute(f"SELECT COUNT(*) FROM {tname}")
    count = cursor.fetchone()[0]
    print(f'{tname}: {count} rows')
    if count > 0:
        cursor.execute(f"SELECT * FROM {tname} LIMIT 3")
        for row in cursor.fetchall():
            print('  ', row[:6])
