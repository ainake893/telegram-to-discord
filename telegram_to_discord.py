import os
os.system("pip install telethon requests deep-translator python-dotenv googletrans==4.0.0-rc1 > /dev/null 2>&1")

from telethon import TelegramClient
from telethon.sessions import StringSession
import requests
import re
import sqlite3
from datetime import timezone, timedelta
from deep_translator import GoogleTranslator
from dotenv import load_dotenv

# --- .env 読み込み ---
load_dotenv()

# --- Telegram API ---
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_string = os.getenv("SESSION_STRING")
client = TelegramClient(StringSession(session_string), api_id, api_hash)

# --- Discord Webhook ---
webhooks = {
    "KudasaiJP": {
        "summary": os.getenv("WEBHOOK_KUDASAI_SUMMARY"),
        "full": os.getenv("WEBHOOK_KUDASAI_FULL")
    },
    "Basedshills28": {"full": os.getenv("WEBHOOK_BASEDSHILLS")},
    "zeegeneracy": {"full": os.getenv("WEBHOOK_ZEGENERACY")},
    "PowsGemCalls": {"full": os.getenv("WEBHOOK_POWSGEMCALLS")},
}

channels = list(webhooks.keys())

# --- 翻訳 ---
translator = GoogleTranslator(source="en", target="ja")

# --- JST ---
JST = timezone(timedelta(hours=9))

# --- DB ---
DB_PATH = "last_id.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS last_ids (channel TEXT PRIMARY KEY, last_id INTEGER)")
conn.commit()

def get_last_id(channel):
    cur.execute("SELECT last_id FROM last_ids WHERE channel = ?", (channel,))
    row = cur.fetchone()
    return row[0] if row else 0

def update_last_id(channel, last_id):
    cur.execute("INSERT OR REPLACE INTO last_ids (channel, last_id) VALUES (?, ?)", (channel, last_id))
    conn.commit()

def translate(text):
    try:
        return translator.translate(text)
    except Exception:
        return f"[翻訳エラー] {text[:200]}..."

def auto_summary(text, dt, sender):
    keywords = (
        r"entry|long|short|buy|sell|SL|TP|指値|成行|利確|損切り|dip|ロング|ショート|meme|ath|"
        r"エアドロ|抽選|タスク|〆切|締切|whitelist|フォーム|KYC|ステーキング|ポイ活|稼ぎ|done|どね|"
        r"ステーキ|🥩|くうう|👀|気になる|神|ama|あま|天才|つおい|やば|脳死"
    )
    sentences = text.split(". ")
    filtered = [s for s in sentences if re.search(keywords, s, re.IGNORECASE)]
    pattern = r"\d+(\.\d+)?\s?(BTC|ETH|USDT|ADA)"
    filtered += [m.group(0) for m in re.finditer(pattern, text)]
    if filtered:
        return f"[{dt}] @{sender} [要約] " + " | ".join(filtered)
    return ""

# --- メイン処理 ---
async def main():
    for channel in channels:
        last_id = get_last_id(channel)
        new_last_id = last_id

        messages = []
        async for message in client.iter_messages(channel, limit=50):
            if message.id <= last_id:
                break
            if message.text:
                jst_time = message.date.astimezone(JST)
                formatted_time = jst_time.strftime("%Y-%m-%d %H:%M:%S")
                sender = (await message.get_sender()).username or "Unknown"
                formatted = f"[{formatted_time}] @{sender}: {message.text}"
                messages.append((message.id, formatted, message.text, formatted_time, sender))

        messages.sort(key=lambda x: x[0])
        if not messages:
            continue

        # --- 全チャンネルまとめ送信方式 ---
        if channel == "KudasaiJP":
            # summary
            summaries = [auto_summary(m[2], m[3], m[4]) for m in messages]
            summaries = [s for s in summaries if s]
            if summaries:
                try:
                    requests.post(webhooks[channel]["summary"], json={"content": "\n".join(summaries[:30])})
                except Exception as e:
                    print(f"❌ Kudasai Summary送信失敗: {e}")

            # full
            full_text = "\n\n".join([m[1] for m in messages])
            if full_text:
                try:
                    requests.post(webhooks[channel]["full"], json={"content": full_text[:1900]})
                except Exception as e:
                    print(f"❌ Kudasai Full送信失敗: {e}")

        else:
            # 他チャンネルもまとめ送信
            full_text = ""
            for m_id, _, text, formatted_time, sender in messages:
                translated = translate(text)
                full_text += f"[{formatted_time}] @{sender}:\n{translated}\n\n"

            if full_text:
                try:
                    requests.post(webhooks[channel]["full"], json={"content": full_text[:1900]})
                except Exception as e:
                    print(f"❌ {channel} Full送信失敗: {e}")

        # --- 最後にlast_idをまとめて更新 ---
        new_last_id = max(m[0] for m in messages)
        update_last_id(channel, new_last_id)
        print(f"✅ 更新完了: {channel} 最終ID {new_last_id}")

# --- 実行 ---
with client:
    client.loop.run_until_complete(main())

conn.close()
