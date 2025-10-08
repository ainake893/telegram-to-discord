import os
# 必要パッケージを起動時に入れる（Render 等の環境で便利）
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

# --- 設定（.env のキー名はあなたが使っているものに合わせる） ---
TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

# Webhook 環境変数名（あなたが貼ってたキー名に合わせている）
# .env に下記キーが入っていることを確認：
# WEBHOOK_BASEDSHILLS
# WEBHOOK_KUDASAI_FULL
# WEBHOOK_KUDASAI_SUMMARY
# WEBHOOK_POWSGEMCALLS
# WEBHOOK_ZEGENERACY
WEBHOOKS = {
    "KudasaiJP": {
        "summary": os.getenv("WEBHOOK_KUDASAI_SUMMARY"),
        "full": os.getenv("WEBHOOK_KUDASAI_FULL")
    },
    "Basedshills28": {"full": os.getenv("WEBHOOK_BASEDSHILLS")},
    "zeegeneracy": {"full": os.getenv("WEBHOOK_ZEGENERACY")},
    "PowsGemCalls": {"full": os.getenv("WEBHOOK_POWSGEMCALLS")},
}

CHANNELS = list(WEBHOOKS.keys())

# --- Translator ---
translator = GoogleTranslator(source="auto", target="ja")

# JST
JST = timezone(timedelta(hours=9))

# --- DB (SQLite) ---
DB_PATH = "last_id.db"
conn = sqlite3.connect(DB_PATH, timeout=30)
cur = conn.cursor()
# channel_state: per-channel tracking of three IDs:
cur.execute("""
CREATE TABLE IF NOT EXISTS channel_state (
  channel TEXT PRIMARY KEY,
  last_id INTEGER DEFAULT 0,        -- master: highest id processed (any notification)
  last_full INTEGER DEFAULT 0,      -- highest id included in "full" notification
  last_summary INTEGER DEFAULT 0    -- highest id included in "summary" notification (Kudasai 用)
)
""")
conn.commit()

def get_state(channel):
    cur.execute("SELECT last_id, last_full, last_summary FROM channel_state WHERE channel = ?", (channel,))
    row = cur.fetchone()
    if row:
        return {"last_id": row[0] or 0, "last_full": row[1] or 0, "last_summary": row[2] or 0}
    # insert default row
    cur.execute("INSERT OR REPLACE INTO channel_state (channel, last_id, last_full, last_summary) VALUES (?,0,0,0)", (channel,))
    conn.commit()
    return {"last_id": 0, "last_full": 0, "last_summary": 0}

def update_state(channel, last_id=None, last_full=None, last_summary=None):
    # 保持は単調増加のみ（古い値で上書きしない）
    st = get_state(channel)
    new_last_id = st["last_id"] if last_id is None else max(st["last_id"], last_id)
    new_last_full = st["last_full"] if last_full is None else max(st["last_full"], last_full)
    new_last_summary = st["last_summary"] if last_summary is None else max(st["last_summary"], last_summary)
    cur.execute("""
        INSERT OR REPLACE INTO channel_state(channel, last_id, last_full, last_summary)
        VALUES (?, ?, ?, ?)
    """, (channel, new_last_id, new_last_full, new_last_summary))
    conn.commit()

def auto_summary(text, dt, sender):
    keywords = (
        r"entry|long|short|buy|sell|SL|TP|指値|成行|利確|損切り|dip|ロング|ショート|meme|ath|"
        r"エアドロ|抽選|タスク|〆切|締切|whitelist|フォーム|KYC|ステーキング|ポイ活|稼ぎ|done|どね|"
        r"ステーキ|🥩|くうう|👀|気になる|神|ama|あま|天才|つおい|やば|脳死"
    )
    sentences = re.split(r'(?<=[。\.!?])\s*', text)  # 少し賢い分割
    filtered = [s for s in sentences if re.search(keywords, s, re.IGNORECASE)]
    pattern = r"\d+(\.\d+)?\s?(BTC|ETH|USDT|ADA)"
    filtered += [m.group(0) for m in re.finditer(pattern, text)]
    if filtered:
        return f"[{dt}] @{sender} [要約] " + " | ".join(filtered)
    return ""

def safe_post(url, json_payload, timeout=10):
    if not url:
        print("❌ webhook URL が未設定です。skipping...")
        return False
    try:
        r = requests.post(url, json=json_payload, timeout=timeout)
        if 200 <= r.status_code < 300:
            return True
        print(f"❌ Webhook returned HTTP {r.status_code}: {r.text}")
    except Exception as e:
        print(f"❌ Webhook POST exception: {e}")
    return False

# --- Telegram client ---
client = TelegramClient(StringSession(SESSION_STRING), TG_API_ID, TG_API_HASH)

async def main():
    async with client:
        for channel in CHANNELS:
            state = get_state(channel)  # 最新の状態を読み直す
            last_id_master = state["last_id"]
            last_full = state["last_full"]
            last_summary = state["last_summary"]
            print(f"[{channel}] state: last_id={last_id_master}, last_full={last_full}, last_summary={last_summary}")

            # 取得（最新→過去）して、処理用に昇順で揃える
            fetched = []
            async for msg in client.iter_messages(channel, limit=200):
                if not msg:
                    continue
                if not getattr(msg, "id", None):
                    continue
                # メッセージ本文がなければスキップ
                text = (msg.message or "").strip()
                if not text:
                    continue
                if msg.id <= min(last_id_master, last_full, last_summary):
                    # 既に全通知済みの最小基準より古ければ省略
                    break
                # get sender username safely
                try:
                    sender = (await msg.get_sender()).username or (getattr(msg.from_id, "user_id", None) or "Unknown")
                except Exception:
                    sender = "Unknown"
                jst_time = msg.date.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")
                fetched.append((msg.id, text, jst_time, sender))

            if not fetched:
                print(f"[{channel}] 新着なし")
                continue

            # 昇順（古い→新しい）
            fetched.sort(key=lambda x: x[0])

            # --- KudasaiJP: summary / full を別管理で送る ---
            if channel == "KudasaiJP":
                # summary 用：last_summary より大きいメッセージを対象
                to_summary = [m for m in fetched if m[0] > last_summary]
                if to_summary:
                    summary_lines = []
                    for mid, text, ftime, sender in to_summary:
                        s = auto_summary(text, ftime, sender)
                        if s and s != "[自動要約] 重要情報なし":
                            summary_lines.append(s)
                    if summary_lines:
                        payload = {"content": "\n".join(summary_lines[:30])}
                        ok = safe_post(WEBHOOKS[channel]["summary"], payload)
                        if ok:
                            max_id = max(m[0] for m in to_summary)
                            update_state(channel, last_summary=max_id)
                            print(f"[{channel}] summary 送信 OK up to {max_id}")
                        else:
                            print(f"[{channel}] summary 送信失敗 (will retry next run)")

                # full 用：last_full より大きいメッセージを対象
                to_full = [m for m in fetched if m[0] > last_full]
                if to_full:
                    full_text = "\n\n".join([f"[{m[2]}] @{m[3]}: {m[1]}" for m in to_full])
                    payload = {"content": full_text[:1900]}
                    ok = safe_post(WEBHOOKS[channel]["full"], payload)
                    if ok:
                        max_id = max(m[0] for m in to_full)
                        update_state(channel, last_full=max_id)
                        print(f"[{channel}] full 送信 OK up to {max_id}")
                    else:
                        print(f"[{channel}] full 送信失敗 (will retry next run)")

                # マスター last_id を summary/full の最大に合わせる（重複防止）
                st = get_state(channel)
                new_master = max(st["last_id"], st["last_full"], st["last_summary"])
                if new_master > st["last_id"]:
                    update_state(channel, last_id=new_master)
                    print(f"[{channel}] master updated to {new_master}")

            else:
                # それ以外のチャンネルは「古い順に1件ずつ送って、成功したら last_id 更新、失敗したらそこで止める」
                webhook_url = WEBHOOKS[channel]["full"]
                for mid, text, ftime, sender in fetched:
                    if mid <= last_id_master:
                        continue  # 既に処理済み
                    translated = translate(text)
                    payload = {"content": f"[{ftime}] @{sender}:\n{translated}"}
                    ok = safe_post(webhook_url, payload)
                    if ok:
                        update_state(channel, last_id=mid)
                        last_id_master = mid
                        print(f"[{channel}] sent OK id={mid}")
                        # 軽いスリープで Discord レートを避ける
                        # （Render の短時間内大量送信を避けるため）
                        # time.sleep(0.2)  # blocking sleep avoided; kept out since this is synchronous in loop
                    else:
                        print(f"[{channel}] send failed id={mid} -> stop processing further messages this run")
                        break

            # ループの次チャンネルへ
            print(f"[{channel}] run finished; state now: {get_state(channel)}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
    conn.close()
