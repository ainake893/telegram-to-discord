from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os
from dotenv import load_dotenv

load_dotenv()
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("新しいセッション文字列を生成中...")
    print("電話番号、ログインコード、2段階認証パスワードを求められます。")
    client.start()
    session_string = client.session.save()
    print("--- 新しい SESSION_STRING ---")
    print(session_string)
    print("-----------------------------")