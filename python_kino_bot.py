import telebot
import re
import sqlite3
from datetime import datetime
from telebot.types import Message

BOT_TOKEN = "8500305736:AAEC-6LeTcgB45ABx9SQ8f9kn8JRuJxxf-c"
CHANNEL_ID = -1003749567746

# Adminlar ro'yxati (o'zingizning Telegram user_id ingizni yozing)
ADMIN_IDS = {0}

DB_FILE = "kino_bot.db"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


# -------------------- DB --------------------
def db_connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

conn = db_connect()
cur = conn.cursor()

def init_db():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS movies (
        code TEXT PRIMARY KEY,
        channel_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        title TEXT,
        created_at TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        chat_id INTEGER NOT NULL,
        username TEXT,
        first_name TEXT,
        joined_at TEXT NOT NULL,
        last_seen TEXT NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        chat_id INTEGER NOT NULL,
        text TEXT,
        created_at TEXT NOT NULL
    )
    """)
    conn.commit()

init_db()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def upsert_user(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    # avval bormi tekshiramiz
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    if row is None:
        cur.execute("""
            INSERT INTO users (user_id, chat_id, username, first_name, joined_at, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, chat_id, username, first_name, now_str(), now_str()))
    else:
        cur.execute("""
            UPDATE users
            SET chat_id = ?, username = ?, first_name = ?, last_seen = ?
            WHERE user_id = ?
        """, (chat_id, username, first_name, now_str(), user_id))

    conn.commit()


def log_message(message: Message):
    text = message.text if message.content_type == "text" else f"[{message.content_type}]"
    cur.execute("""
        INSERT INTO messages (user_id, chat_id, text, created_at)
        VALUES (?, ?, ?, ?)
    """, (message.from_user.id, message.chat.id, text, now_str()))
    conn.commit()


def extract_code(text: str):
    """
    Kod formatlari:
      - kodi: 2 / KODI:2 / kodi 2 / kodi-2
      - kod: 2 / KOD:2
      - #2
      - faqat 2 (oddiy raqam)
    """
    if not text:
        return None

    # kodi: 123
    m = re.search(r"(?i)\bkodi\s*[:\-]?\s*(\d{1,12})\b", text)
    if m:
        return m.group(1)

    # kod: 123
    m = re.search(r"(?i)\bkod\s*[:\-]?\s*(\d{1,12})\b", text)
    if m:
        return m.group(1)

    # #123
    m = re.search(r"#(\d{1,12})\b", text)
    if m:
        return m.group(1)

    # faqat raqam bo'lsa: "123"
    t = text.strip()
    if re.fullmatch(r"\d{1,12}", t):
        return t

    return None


def save_movie(code: str, channel_id: int, message_id: int, title: str):
    # code PRIMARY KEY bo'lgani uchun "yangilash" ham bo'ladi
    cur.execute("""
        INSERT INTO movies (code, channel_id, message_id, title, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
          channel_id=excluded.channel_id,
          message_id=excluded.message_id,
          title=excluded.title,
          created_at=excluded.created_at
    """, (code, channel_id, message_id, title, now_str()))
    conn.commit()


def get_movie(code: str):
    cur.execute("SELECT * FROM movies WHERE code = ?", (code,))
    return cur.fetchone()


# -------------------- Channel posts: indekslash --------------------
@bot.channel_post_handler(content_types=["text", "video", "document", "photo", "animation", "audio"])
def handle_channel_post(message: Message):
    if message.chat.id != CHANNEL_ID:
        return

    text = message.text or message.caption or ""
    code = extract_code(text)
    if not code:
        return

    title = ""
    if text.strip():
        title = text.strip().splitlines()[0][:120]

    save_movie(code, message.chat.id, message.message_id, title)


# -------------------- User flow --------------------
user_state = {}  # user_id -> waiting_code

@bot.message_handler(commands=["start"])
def start(message: Message):
    upsert_user(message)
    log_message(message)

    bot.send_message(
        message.chat.id,
        "🎬 <b>Kino bot</b>\n\n"
        "Kino kodini yuboring (masalan: <b>2</b> yoki <b>KOD:2</b>).\n"
        "📌 Kodni yuboring"
    )

@bot.message_handler(commands=["kod"])
def ask_code(message: Message):
    upsert_user(message)
    log_message(message)

    user_state[message.from_user.id] = "waiting_code"
    bot.send_message(message.chat.id, "✅ Kino kodini yuboring (masalan: 2):")


@bot.message_handler(commands=["stats"])
def stats(message: Message):
    upsert_user(message)
    log_message(message)

    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "⛔ Sizda ruxsat yo‘q.")
        return

    cur.execute("SELECT COUNT(*) as c FROM users")
    users_count = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM movies")
    movies_count = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM messages")
    msg_count = cur.fetchone()["c"]

    bot.send_message(
        message.chat.id,
        "📊 <b>Statistika</b>\n"
        f"👥 Obunachilar (botni ishlatganlar): <b>{users_count}</b>\n"
        f"🎞 Bazadagi kinolar (kodlar): <b>{movies_count}</b>\n"
        f"💬 Log qilingan xabarlar: <b>{msg_count}</b>\n"
        f"📌 Kanal: <b>{CHANNEL_ID}</b>"
    )


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message: Message):
    upsert_user(message)
    log_message(message)

    text = (message.text or "").strip()

    waiting = (user_state.get(message.from_user.id) == "waiting_code")
    is_code_like = bool(re.fullmatch(r"(?:\s*(?:KOD\s*[:\-]?\s*)?\d{1,6}\s*)|(?:\s*#\d{1,6}\s*)", text, flags=re.I))

    if waiting or is_code_like:
        code = extract_code(text)
        if not code:
            bot.send_message(message.chat.id, "❌ Kodni tushunmadim. Masalan: <b>2</b> yoki <b>KOD: 2</b>")
            return

        item = get_movie(code)
        if not item:
            bot.send_message(message.chat.id, f"❌ <b>{code}</b> kodi topilmadi.")
            user_state.pop(message.from_user.id, None)
            return

        try:
            # FORWARD - video ham, photo ham, doc ham hammasi ketadi
            bot.forward_message(
                chat_id=message.chat.id,
                from_chat_id=item["channel_id"],
                message_id=item["message_id"]
            )
            bot.send_message(message.chat.id, f"✅ <b>{code}</b> kodi yuborildi.")
        except Exception as e:
            bot.send_message(
                message.chat.id,
                "❌ Yuborib bo‘lmadi.\n"
                "Tekshiring:\n"
                "1) Bot kanalga admin qilinganmi?\n"
                "2) Kanalda kontentni saqlash/forward cheklovi yo‘qmi?\n"
                "3) Foydalanuvchi botni /start qilganmi?\n\n"
                f"Xatolik: <code>{e}</code>"
            )

        user_state.pop(message.from_user.id, None)
        return

    bot.send_message(message.chat.id, "🎬 Kino kodini yuboring (masalan: <b>2</b>) yoki /kod bosing.")


print("Kino bot ishga tushdi...")
bot.infinity_polling(skip_pending=True)
