import os
import requests 
import json     
from telethon import TelegramClient
from telethon.sessions import StringSession
import re
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

# --- DB (GitHub Gistを利用する方法) ---
GIST_ID = os.getenv("GIST_ID")
GIST_TOKEN = os.getenv("GIST_TOKEN")
GIST_URL = f"https://api.github.com/gists/{GIST_ID}"
HEADERS = {
    "Authorization": f"token {GIST_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}
FILENAME = "last_ids.json"

# グローバル変数でlast_idsをメモリに保持
_last_ids_cache = {}

def load_last_ids_from_gist():
    """GistからIDデータを読み込む"""
    global _last_ids_cache
    try:
        res = requests.get(GIST_URL, headers=HEADERS)
        res.raise_for_status()
        gist_data = res.json()
        if FILENAME in gist_data["files"]:
            content = gist_data["files"][FILENAME]["content"]
            _last_ids_cache = json.loads(content)
            print(f"Gistからlast_idsを読み込みました: {_last_ids_cache}")
        else:
            print(f"Gistに {FILENAME} が見つかりません。初回実行として扱います。")
            _last_ids_cache = {}
    except Exception as e:
        print(f"❌ Gistからの読み込みに失敗: {e}")
        _last_ids_cache = {} # エラー時は空で初期化

def update_gist():
    """メモリ上のIDデータをGistに書き込む"""
    try:
        data = {
            "files": {
                FILENAME: {
                    "content": json.dumps(_last_ids_cache, indent=2)
                }
            }
        }
        res = requests.patch(GIST_URL, headers=HEADERS, json=data)
        res.raise_for_status()
        print(f"Gistへのlast_idsの書き込みに成功: {_last_ids_cache}")
    except Exception as e:
        print(f"❌ Gistへの書き込みに失敗: {e}")

def get_last_id(channel):
    """キャッシュから特定のチャンネルのlast_idを取得"""
    return _last_ids_cache.get(channel, 0)

def update_last_id(channel, last_id):
    """キャッシュ上の特定のチャンネルのlast_idを更新"""
    _last_ids_cache[channel] = last_id
# --- DB処理ここまで ---

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

# --- ★★★ メッセージ取得に制限を追加 (重要) ★★★ ---
async def process_channel(channel):
    last_id = get_last_id(channel)
    new_last_id = last_id

    messages = []
    # offset_id と reverse=True を使い、前回の続きから古い順に最大1000件取得
    async for message in client.iter_messages(channel, offset_id=last_id, reverse=True, limit=1000):
        if message.text:
            jst_time = message.date.astimezone(JST)
            formatted_time = jst_time.strftime("%Y-%m-%d %H:%M:%S")

            sender_obj = await message.get_sender()
            sender = sender_obj.username if sender_obj and sender_obj.username else "Unknown"

            messages.append((message.id, message.text, formatted_time, sender))
            # 取得したメッセージの中で一番新しいIDを一時的に保持
            new_last_id = message.id 

    if not messages:
        print(f"[{channel}] 新規メッセージなし")
        return

    # --- KudasaiJP だけ summary 生成 ---
    if channel == "KudasaiJP":
        summaries = [auto_summary(m[1], m[2], m[3]) for m in messages]
        summaries = [s for s in summaries if s]
        if summaries:
            try:
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
        chunk_size = 1900
        chunk = []
        current_length = 0
        for line in full_texts:
            line_len = len(line.encode('utf-8')) + 1
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

    # --- 最後に last_id 更新 (メモリ上) ---
    update_last_id(channel, new_last_id)
    print(f"[{channel}] last_id 更新 {new_last_id}")


# --- Gist対応の main 関数 ---
async def main():
    load_last_ids_from_gist() # 最初にGistからデータを読み込む
    for channel in channels:
        await process_channel(channel)
    update_gist() # 最後にまとめてGistに書き込む

with client:
    client.loop.run_until_complete(main())