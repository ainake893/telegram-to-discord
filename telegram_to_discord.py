from telethon import TelegramClient
from telethon.sessions import StringSession
import requests
import re
import os
from datetime import timezone, timedelta
from deep_translator import DeeplTranslator
from dotenv import load_dotenv

# --- .env 読み込み ---
load_dotenv()

# --- Telegram API ---
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH"))
session_string = os.getenv("SESSION_STRING")
client = TelegramClient(StringSession(session_string), api_id, api_hash)

# --- Discord Webhook ---
webhooks = {
    "KudasaiJP_summary": os.getenv("WEBHOOK_KUDASAI_SUMMARY"),
    "KudasaiJP_full": os.getenv("WEBHOOK_KUDASAI_FULL"),
    "Basedshills28": os.getenv("WEBHOOK_BASEDSHILLS"),
    "zeegeneracy": os.getenv("WEBHOOK_ZEGENERACY"),
    "PowsGemCalls": os.getenv("WEBHOOK_POWSGEMCALLS")
}

channels = ["KudasaiJP", "Basedshills28", "zeegeneracy", "PowsGemCalls"]

# --- DeepL Translator ---
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
translator = DeeplTranslator(api_key=DEEPL_API_KEY, source="english", target="japanese")

# JSTタイムゾーン
JST = timezone(timedelta(hours=9))

# --- 翻訳関数 ---
def translate(text):
    try:
        return translator.translate(text)
    except Exception:
        return f"[翻訳エラー] {text[:200]}..."

# --- 自動要約関数（キーワード抽出） ---
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
        messages = []
        async for message in client.iter_messages(channel, limit=50):
            if message.text:
                jst_time = message.date.astimezone(JST)
                formatted_time = jst_time.strftime("%Y-%m-%d %H:%M:%S")
                sender = (await message.get_sender()).username or "Unknown"
                formatted = f"[{formatted_time}] @{sender}: {message.text}"
                messages.append((message.id, formatted, message.text, formatted_time, sender))

        messages.sort(key=lambda x: x[0])

        if channel == "KudasaiJP":
            summaries = [auto_summary(m[2], m[3], m[4]) for m in messages]
            summaries = [s for s in summaries if s]
            if summaries:
                requests.post(webhooks["KudasaiJP_summary"], json={"content": "\n".join(summaries[:30])})

            full_text = "\n\n".join([m[1] for m in messages])
            if full_text:
                requests.post(webhooks["KudasaiJP_full"], json={"content": full_text[:1900]})
        else:
            for _, _, text, formatted_time, sender in messages:
                translated = translate(text)
                content = f"[{formatted_time}] @{sender}:\n{translated}"
                requests.post(webhooks[channel], json={"content": content})

# --- 実行 ---
with client:
    client.loop.run_until_complete(main())
