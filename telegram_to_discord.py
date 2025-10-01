from telethon import TelegramClient
import requests
import re
import os
from datetime import timezone, timedelta
from deep_translator import DeeplTranslator

# --- Telegram API ---
api_id = 22898247
api_hash = "59fa1ab5063d5d30306605a0fe7934f0"
client = TelegramClient("my_session", api_id, api_hash)

# --- Discord Webhook ---
webhooks = {
    "KudasaiJP_summary": "https://discord.com/api/webhooks/1421660892185100402/p-SZ1A5UDY6lTmzLiJitdcK0dy2WHJnCzqH9Egncdi9Xl09nsoAJ_AJjqXY7lCIIlTci",
    "KudasaiJP_full": "https://discord.com/api/webhooks/1421672954433114162/6irw9Je6LaC2M6khpmcOLo5s6bacTLgE-LyiTU7cvuo0gid_BoL1fwl7X7OCeAoAXsWi",
    "Basedshills28": "https://discord.com/api/webhooks/1421666909778346026/cn9lBHXn_f0J1iQFowWOzy2xijU7Wp_sKvBFIBsFqfpPd42h0ie14l9NMdxA3GkBLAoT",
    "zeegeneracy": "https://discord.com/api/webhooks/1421667024593092773/y_O5LOopcsyqCgBLZomhv9Gm5P6WePG9r8r6rHQPomEwotqO_bwiT4biSPyQMdzrNR7-",
    "PowsGemCalls": "https://discord.com/api/webhooks/1421667047586271386/gC1v-wkfZeJ2LrS2Bt6dOgLKdafKzJbsGoV_QnqgbjU173DjSsVDGkepUp7o4EjdgAKP"
}

channels = ["KudasaiJP", "Basedshills28", "zeegeneracy", "PowsGemCalls"]

# --- DeepL Translator ---
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
translator = DeeplTranslator(api_key=DEEPL_API_KEY, source="english", target="japanese")

# JSTタイムゾーン
JST = timezone(timedelta(hours=9))

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

async def main():
    for channel in channels:
        messages = []
        async for message in client.iter_messages(channel, limit=50):
            if message.text:
                # JSTに変換
                jst_time = message.date.astimezone(JST)
                formatted_time = jst_time.strftime("%Y-%m-%d %H:%M:%S")
                sender = (await message.get_sender()).username or "Unknown"
                formatted = f"[{formatted_time}] @{sender}: {message.text}"
                messages.append((message.id, formatted, message.text, formatted_time, sender))

        # 古い順に並び替え
        messages.sort(key=lambda x: x[0])

        if channel == "KudasaiJP":
            # --- 要約（キーワード抜き出し）
            summaries = [auto_summary(m[2], m[3], m[4]) for m in messages]
            summaries = [s for s in summaries if s]
            if summaries:
                requests.post(webhooks["KudasaiJP_summary"], json={"content": "\n".join(summaries[:30])})

            # --- 全文まとめ
            full_text = "\n\n".join([m[1] for m in messages])
            if full_text:
                requests.post(webhooks["KudasaiJP_full"], json={"content": full_text[:1900]})
        else:
            # --- 翻訳付き送信（日時＋送信者付き）
            for _, _, text, formatted_time, sender in messages:
                translated = translate(text)
                content = f"[{formatted_time}] @{sender}:\n{translated}"
                requests.post(webhooks[channel], json={"content": content})

with client:
    client.loop.run_until_complete(main())