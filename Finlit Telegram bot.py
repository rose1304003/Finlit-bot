# -*- coding: utf-8 -*-
"""
Finlit Networking – Registration Bot (single-file)

Features
- Step-by-step registration (Uzbek Latin prompts)
- Multi-select for Networking goals and Languages (inline buttons)
- Single-select for preferred format (inline buttons)
- Saves all registrations into SQLite (data/finlit.db)
- Auto-exports/updates Excel (data/registrations.xlsx)
- DMs every completed registration to ORGANIZER_IDS
- Admin commands: /stats, /export_excel, /whoami, /help

Requires
    pip install python-telegram-bot==21.4 pandas openpyxl python-dotenv

Env (.env)
    TELEGRAM_BOT_TOKEN=123456:AA...
    ORGANIZER_IDS=111111111,222222222   # comma-separated Telegram user IDs
    EXCEL_PATH=data/registrations.xlsx  # optional; default as shown
    LOCAL_TZ=Asia/Tashkent             # optional; default as shown

Run
    python finlit_registration_bot.py
"""
from __future__ import annotations
import os
import logging
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Set, Dict

import pandas as pd
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ---------------------- Setup & Config ----------------------
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")

LOCAL_TZ = os.getenv("LOCAL_TZ", "Asia/Tashkent")
TZ = ZoneInfo(LOCAL_TZ)

EXCEL_PATH = os.getenv("EXCEL_PATH", "data/registrations.xlsx")
DATA_DIR = Path(EXCEL_PATH).parent
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "finlit.db"

def parse_admins(raw: str | None) -> List[int]:
    if not raw:
        return []
    ids: List[int] = []
    for part in raw.split(','):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                pass
    return ids

ORGANIZER_IDS: List[int] = parse_admins(os.getenv("ORGANIZER_IDS"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("finlit-bot")

# ---------------------- DB Layer ----------------------
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    telegram_username TEXT,
    full_name TEXT,
    workplace TEXT,
    career_field TEXT,
    interests TEXT,
    networking_goals TEXT,
    region TEXT,
    languages TEXT,
    topics TEXT,
    meet_format TEXT,
    self_desc TEXT,
    created_at TEXT
);
"""

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def ensure_db() -> None:
    with db_connect() as c:
        c.execute(SCHEMA_SQL)

@dataclass
class Registration:
    telegram_id: int
    telegram_username: str | None
    full_name: str
    workplace: str
    career_field: str
    interests: str
    networking_goals: str  # comma-separated
    region: str
    languages: str         # comma-separated
    topics: str
    meet_format: str
    self_desc: str
    created_at: str        # ISO local time string

    @staticmethod
    def from_context(context: ContextTypes.DEFAULT_TYPE, update: Update) -> "Registration":
        ud = context.user_data
        now_local = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
        user = update.effective_user
        return Registration(
            telegram_id=user.id,
            telegram_username=user.username,
            full_name=ud.get("full_name", ""),
            workplace=ud.get("workplace", ""),
            career_field=ud.get("career_field", ""),
            interests=ud.get("interests", ""),
            networking_goals=", ".join(sorted(ud.get("networking_selected", set()))),
            region=ud.get("region", ""),
            languages=", ".join(sorted(ud.get("languages_selected", set())) + ([ud.get("languages_text")] if ud.get("languages_text") else [])),
            topics=ud.get("topics", ""),
            meet_format=ud.get("meet_format", ""),
            self_desc=ud.get("self_desc", ""),
            created_at=now_local,
        )

    def save(self) -> None:
        with db_connect() as c:
            c.execute(
                """
                INSERT INTO registrations (
                    telegram_id, telegram_username, full_name, workplace, career_field,
                    interests, networking_goals, region, languages, topics, meet_format,
                    self_desc, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.telegram_id, self.telegram_username, self.full_name, self.workplace,
                    self.career_field, self.interests, self.networking_goals, self.region,
                    self.languages, self.topics, self.meet_format, self.self_desc, self.created_at,
                ),
            )

# ---------------------- Excel Export ----------------------
def export_to_excel(path: str | Path = EXCEL_PATH) -> Path:
    with db_connect() as c:
        df = pd.read_sql_query("SELECT * FROM registrations ORDER BY id DESC", c)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
    return path

# ---------------------- Helpers ----------------------
NETWORKING_OPTIONS = [
    "Yangi tanishlar",
    "Hamkorlik imkoniyatlari",
    "Tajriba almashish",
    "Ilhom va g‘oyalar",
]

LANGUAGE_OPTIONS = [
    "O‘zbekcha",
    "Ruscha",
    "Inglizcha",
]

FORMAT_OPTIONS = [
    "Oflayn uchrashuv",
    "Onlayn format",
    "Gibrid",
]

# Conversation states
(
    NAME,
    WORKPLACE,
    CAREER,
    INTERESTS,
    NETWORKING,
    REGION,
    LANGUAGES,
    LANGUAGES_TEXT,
    TOPICS,
    MEET_FORMAT,
    SELF_DESC,
    CONFIRM,
) = range(12)


def is_admin(user_id: int) -> bool:
    return user_id in ORGANIZER_IDS


def bold(s: str) -> str:
    return f"<b>{s}</b>"


def make_multiselect_kb(options: List[str], selected: Set[str], with_done: bool = True, with_text_alt: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for opt in options:
        mark = "☑️" if opt in selected else "⬜️"
        rows.append([InlineKeyboardButton(text=f"{mark} {opt}", callback_data=f"opt::{opt}")])
    extra = []
    if with_text_alt:
        extra.append(InlineKeyboardButton("✍️ Boshqa (yozib kiriting)", callback_data="alt::text"))
    if with_done:
        extra.append(InlineKeyboardButton("✅ Tayyor", callback_data="done::ok"))
    if extra:
        rows.append(extra)
    return InlineKeyboardMarkup(rows)


def make_singleselect_kb(options: List[str]) -> InlineKeyboardMarkup:
    rows = []
    for opt in options:
        rows.append([InlineKeyboardButton(text=opt, callback_data=f"pick::{opt}")])
    return InlineKeyboardMarkup(rows)


def registration_summary(reg: Registration) -> str:
    ulink = f"@{reg.telegram_username}" if reg.telegram_username else str(reg.telegram_id)
    return (
        f"✅ {bold('Yangi ro‘yxatdan o‘tish!')}\n"
        f"{bold('Foydalanuvchi')}: {ulink}\n\n"
        f"{bold('👤 Ism-familiya')}: {reg.full_name}\n"
        f"{bold('🏢 Ish/o‘qish joyi')}: {reg.workplace}\n"
        f"{bold('💼 Kasbiy yo‘nalish')}: {reg.career_field}\n"
        f"{bold('📊 Qiziq sohalar')}: {reg.interests}\n"
        f"{bold('🤝 Networking maqsadi')}: {reg.networking_goals}\n"
        f"{bold('🌍 Hudud')}: {reg.region}\n"
        f"{bold('🗣 Tillar')}: {reg.languages}\n"
        f"{bold('🚀 Qiziqqan mavzular')}: {reg.topics}\n"
        f"{bold('📱 Qulay format')}: {reg.meet_format}\n"
        f"{bold('✨ Bir og‘izda')}: {reg.self_desc}\n\n"
        f"{bold('Sana/vaqt')}: {reg.created_at} ({LOCAL_TZ})"
    )

# ---------------------- Handlers: Core Flow ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Salom! Finlit Networking ro‘yxatdan o‘tish uchun quyidagi savollarga javob bering.\n\n"
        "Boshlaymiz. Avvalo, "
        "👤 Ismingiz va familiyangizni yuboring:")
    return NAME

async def ask_workplace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["full_name"] = update.message.text.strip()
    await update.message.reply_text("🏢 Qaerda ishlaysiz yoki o‘qiysiz? (tashkilot/universitet nomi)")
    return WORKPLACE

async def ask_career(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["workplace"] = update.message.text.strip()
    await update.message.reply_text("💼 Sizning kasbiy yo‘nalishingiz?")
    return CAREER

async def ask_interests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["career_field"] = update.message.text.strip()
    await update.message.reply_text("📊 Qaysi moliyaviy yoki iqtisodiy sohalar siz uchun eng qiziqarli?")
    return INTERESTS

async def ask_networking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["interests"] = update.message.text.strip()
    context.user_data["networking_selected"] = set()
    kb = make_multiselect_kb(NETWORKING_OPTIONS, set(), with_done=True, with_text_alt=False)
    await update.message.reply_text(
        "🤝 Networkingdan qanday maqsadda qatnashmoqchisiz? Bir nechta bandni tanlashingiz mumkin:",
        reply_markup=kb,
    )
    return NETWORKING

async def on_networking_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    selected: Set[str] = context.user_data.get("networking_selected", set())
    if data.startswith("opt::"):
        val = data.split("::", 1)[1]
        if val in selected:
            selected.remove(val)
        else:
            selected.add(val)
        context.user_data["networking_selected"] = selected
        await q.edit_message_reply_markup(make_multiselect_kb(NETWORKING_OPTIONS, selected))
        return NETWORKING
    elif data == "done::ok":
        if not selected:
            await q.reply_text("Kamida bitta maqsadni tanlang, iltimos.")
            return NETWORKING
        await q.message.reply_text("🌍 Qaysi hududdan qatnashyapsiz?")
        return REGION

async def ask_languages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["region"] = update.message.text.strip()
    context.user_data["languages_selected"] = set()
    kb = make_multiselect_kb(LANGUAGE_OPTIONS, set(), with_done=True, with_text_alt=True)
    await update.message.reply_text(
        "🗣 Qaysi tillarda muloqot qilish qulay? Bir nechta bandni tanlang yoki \"Boshqa\" ni bosing.",
        reply_markup=kb,
    )
    return LANGUAGES

async def on_languages_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    selected: Set[str] = context.user_data.get("languages_selected", set())
    if data.startswith("opt::"):
        val = data.split("::", 1)[1]
        if val in selected:
            selected.remove(val)
        else:
            selected.add(val)
        context.user_data["languages_selected"] = selected
        await q.edit_message_reply_markup(make_multiselect_kb(LANGUAGE_OPTIONS, selected, with_done=True, with_text_alt=True))
        return LANGUAGES
    elif data == "alt::text":
        await q.message.reply_text("✍️ Qaysi boshqa tillar? Matn ko‘rinishida yozing (masalan: Nemischa, Turkcha).")
        return LANGUAGES_TEXT
    elif data == "done::ok":
        if not selected and not context.user_data.get("languages_text"):
            await q.message.reply_text("Iltimos, kamida bitta tilni tanlang yoki yozib yuboring.")
            return LANGUAGES
        await q.message.reply_text("🚀 Finlit Networking davomida qaysi mavzular muhokama qilinishiga qiziqasiz?")
        return TOPICS

async def languages_text_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["languages_text"] = update.message.text.strip()
    await update.message.reply_text("🚀 Finlit Networking davomida qaysi mavzular muhokama qilinishiga qiziqasiz?")
    return TOPICS

async def ask_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["topics"] = update.message.text.strip()
    kb = make_singleselect_kb(FORMAT_OPTIONS)
    await update.message.reply_text("📱 Sizga qaysi format qulayroq:", reply_markup=kb)
    return MEET_FORMAT

async def on_format_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("pick::"):
        picked = data.split("::", 1)[1]
        context.user_data["meet_format"] = picked
        await q.message.reply_text("✨ Bir og‘izda o‘zingizni qanday ifoda etgan bo‘lardingiz? (Masalan: \"Men – ...\")")
        return SELF_DESC

async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["self_desc"] = update.message.text.strip()
    reg = Registration.from_context(context, update)

    text = (
        f"{bold('Tekshiring:')}\n\n"
        f"{bold('👤 Ism-familiya')}: {reg.full_name}\n"
        f"{bold('🏢 Ish/o‘qish joyi')}: {reg.workplace}\n"
        f"{bold('💼 Kasbiy yo‘nalish')}: {reg.career_field}\n"
        f"{bold('📊 Qiziq sohalar')}: {reg.interests}\n"
        f"{bold('🤝 Networking maqsadi')}: {reg.networking_goals}\n"
        f"{bold('🌍 Hudud')}: {reg.region}\n"
        f"{bold('🗣 Tillar')}: {reg.languages}\n"
        f"{bold('🚀 Mavzular')}: {reg.topics}\n"
        f"{bold('📱 Format')}: {reg.meet_format}\n"
        f"{bold('✨ Men –')}: {reg.self_desc}\n\n"
        "Hammasi to‘g‘rimi?"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash", callback_data="confirm::yes")],
        [InlineKeyboardButton("↩️ Qayta boshlash", callback_data="confirm::restart")],
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return CONFIRM

async def on_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "confirm::restart":
        # Reset and start over
        context.user_data.clear()
        await q.message.reply_text("Qaytadan boshlaymiz. 👤 Ismingiz va familiyangiz?")
        return NAME
    elif data == "confirm::yes":
        reg = Registration.from_context(context, update)
        reg.save()
        # Export (update) Excel silently
        try:
            export_to_excel(EXCEL_PATH)
        except Exception as e:
            log.warning("Excel export failed: %s", e)
        # Send receipts
        user_msg = (
            f"✅ Ro‘yxatdan o‘tish tugadi!\n\n" + registration_summary(reg)
        )
        await q.message.reply_text(user_msg, parse_mode=ParseMode.HTML)
        # DM to organizers
        for admin_id in ORGANIZER_IDS:
            try:
                await q.bot.send_message(chat_id=admin_id, text=registration_summary(reg), parse_mode=ParseMode.HTML)
            except Exception as e:
                log.warning("Failed to DM organizer %s: %s", admin_id, e)
        return ConversationHandler.END

# ---------------------- Handlers: Admin & Utility ----------------------
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"Sizning user id: {u.id}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "\n".join([
            "Buyruqlar:",
            "/start — ro‘yxatdan o‘tishni boshlash",
            "/whoami — user id ni ko‘rsatish",
            "/stats — (admin) registratsiyalar statistikasi",
            "/export_excel — (admin) Excel faylni yuborish",
        ])
    )
    await update.message.reply_text(txt)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")

    with db_connect() as c:
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM registrations")
        total = cur.fetchone()[0]
        # simple local-day filter in Python
        cur.execute("SELECT created_at FROM registrations")
        rows = [r[0] for r in cur.fetchall()]

    now = datetime.now(TZ)
    today = now.date()
    start_of_week = (now - timedelta(days=now.weekday())).date()

    today_count = 0
    week_count = 0
    for s in rows:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").date()
        except Exception:
            continue
        if dt == today:
            today_count += 1
        if dt >= start_of_week:
            week_count += 1

    await update.message.reply_text(
        f"📊 Statistikalar:\n"
        f"Jami: {total}\n"
        f"Bugun: {today_count}\n"
        f"Ushbu hafta: {week_count}"
    )

async def export_excel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
    path = export_to_excel(EXCEL_PATH)
    try:
        await update.message.reply_document(document=path.open('rb'), filename=Path(EXCEL_PATH).name, caption="Registratsiyalar (Excel)")
    except Exception as e:
        await update.message.reply_text(f"Yuborishda xatolik: {e}")

# ---------------------- Cancel / Fallback ----------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi. /start orqali qayta boshlashingiz mumkin.")
    return ConversationHandler.END

# ---------------------- Main ----------------------
def build_app() -> Application:
    ensure_db()

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_workplace)],
            WORKPLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_career)],
            CAREER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_interests)],
            INTERESTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_networking)],
            NETWORKING: [CallbackQueryHandler(on_networking_cb)],
            REGION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_languages)],
            LANGUAGES: [CallbackQueryHandler(on_languages_cb)],
            LANGUAGES_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, languages_text_done)],
            TOPICS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_format)],
            MEET_FORMAT: [CallbackQueryHandler(on_format_cb)],
            SELF_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm)],
            CONFIRM: [CallbackQueryHandler(on_confirm_cb)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("export_excel", export_excel_cmd))

    return app


def main():
    app = build_app()
    log.info("Finlit Registration Bot started. Organizers: %s", ORGANIZER_IDS)
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
