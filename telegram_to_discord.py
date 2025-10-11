import os
from telethon import TelegramClient
from telethon.sessions import StringSession
import requests
import re
import psycopg2 # sqlite3 の代わりに psycopg2 をインポート
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
    "PowsGemCalls": {"full": os.getenv("WEBHOOK_POWSGEMCALLS")}
}

channels = list(webhooks.keys())

# --- 翻訳 ---
translator = GoogleTranslator(source="en", target="ja")

# --- JST ---
JST = timezone(timedelta(hours=9))

# --- DB (PostgreSQL に完全対応) ---
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# テーブルがなければ作成する (BIGINTは大きな整数を扱える型)
cur.execute("CREATE TABLE IF NOT EXISTS last_ids (channel VARCHAR(255) PRIMARY KEY, last_id BIGINT)")
conn.commit()

def get_last_id(channel):
    # SQLのプレースホルダを %s に変更
    cur.execute("SELECT last_id FROM last_ids WHERE channel = %s", (channel,))
    row = cur.fetchone()
    return row[0] if row else 0

def update_last_id(channel, last_id):
    # PostgreSQLの構文 INSERT ... ON CONFLICT を使用して、あれば更新、なければ挿入
    cur.execute("""
        INSERT INTO last_ids (channel, last_id) VALUES (%s, %s)
        ON CONFLICT (channel) DO UPDATE SET last_id = EXCLUDED.last_id
    """, (channel, last_id))
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

async def process_channel(channel):
    last_id = get_last_id(channel)
    new_last_id = last_id

    messages = []
    async for message in client.iter_messages(channel, limit=50):
        if message.id <= last_id:
            break
        if message.text:
            jst_time = message.date.astimezone(JST)
            formatted_time = jst_time.strftime("%Y-%m-%d %H:%M:%S")

            # senderがNoneの場合のエラーを回避するコード
            sender_obj = await message.get_sender()
            sender = sender_obj.username if sender_obj and sender_obj.username else "Unknown"

            messages.append((message.id, message.text, formatted_time, sender))

    if not messages:
        print(f"[{channel}] 新規メッセージなし")
        return

    messages.sort(key=lambda x: x[0])
    new_last_id = max(m[0] for m in messages)

    # --- KudasaiJP だけ summary 生成 ---
    if channel == "KudasaiJP":
        summaries = [auto_summary(m[1], m[2], m[3]) for m in messages]
        summaries = [s for s in summaries if s]
        if summaries:
            try:
                # 結合後の文字列が長くなりすぎないように調整
                content = "\n".join(summaries)
                if len(content) > 2000:
                    content = content[:1990] + "..."
                requests.post(webhooks[channel]["summary"], json={"content": content})
                print(f"[{channel}] summary 送信 OK up to {new_last_id}")
            except Exception as e:
                print(f"❌ {channel} summary 送信失敗: {e}")

    # --- 全メッセージを full にまとめて送信 ---
    full_texts = []
    for _, text, formatted_time, sender in messages:
        translated = translate(text)
        full_texts.append(f"[{formatted_time}] @{sender}:\n{translated}")

    try:
        chunk_size = 1900 # Discordの制限を考慮して少し余裕を持たせる
        chunk = []
        current_length = 0
        for line in full_texts:
            line_len = len(line.encode('utf-8')) + 1 # バイト数で計算
            if current_length + line_len > chunk_size and chunk:
                requests.post(webhooks[channel]["full"], json={"content": "\n".join(chunk)})
                chunk = [line]
                current_length = line_len
            else:
                chunk.append(line)
                current_length += line_len
        
        if chunk:
            requests.post(webhooks[channel]["full"], json={"content": "\n".join(chunk)})
        
        print(f"[{channel}] full 送信 OK up to {new_last_id}")
    except Exception as e:
        print(f"❌ {channel} full 送信失敗: {e}")

    # --- 最後に last_id 更新 ---
    update_last_id(channel, new_last_id)
    print(f"[{channel}] last_id 更新 {new_last_id}")

async def main():
    for channel in channels:
        await process_channel(channel)

with client:
    client.loop.run_until_complete(main())

conn.close()