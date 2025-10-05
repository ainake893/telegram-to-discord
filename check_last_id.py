import sqlite3

DB_PATH = "last_id.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS last_ids (channel TEXT PRIMARY KEY, last_id INTEGER)")
conn.commit()

# テスト書き込み
cur.execute("INSERT OR REPLACE INTO last_ids (channel, last_id) VALUES (?, ?)", ("TestChannel", 12345))
conn.commit()

# 確認
cur.execute("SELECT * FROM last_ids")
rows = cur.fetchall()
print("DBの内容:", rows)

conn.close()
