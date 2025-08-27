# -*- coding: utf-8 -*-
"""
Finlit Networking – Registration Bot (MySQL via storage.py)
Now asks for PHONE after format, and finishes (no 'topics'/'self_desc' questions).
Phone is stored in the DB's 'topics' column for compatibility.
"""

from __future__ import annotations
import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Set

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

# --- storage layer (MySQL) ---
# Keep storage.py (MySQL) in the same folder.
from storage import ensure_db, Registration, export_to_excel, db_connect

# ---------------------- Setup & Config ----------------------
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")

LOCAL_TZ = os.getenv("LOCAL_TZ", "Asia/Tashkent")
TZ = ZoneInfo(LOCAL_TZ)

EXCEL_PATH = os.getenv("EXCEL_PATH", "data/registrations.xlsx")

def parse_admins(raw: str | None) -> List[int]:
    if not raw:
        return []
    ids: List[int] = []
    for part in raw.split(","):
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

# Conversation states (TOPICS/SELF_DESC removed; add PHONE)
(
    NAME,
    WORKPLACE,
    CAREER,
    INTERESTS,
    NETWORKING,
    REGION,
    LANGUAGES,
    LANGUAGES_TEXT,
    MEET_FORMAT,
    PHONE,
) = range(10)

def is_admin(user_id: int) -> bool:
    return user_id in ORGANIZER_IDS

def bold(s: str) -> str:
    return f"<b>{s}</b>"

def make_multiselect_kb(
    options: List[str],
    selected: Set[str],
    with_done: bool = True,
    with_text_alt: bool = False
) -> InlineKeyboardMarkup:
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
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=opt, callback_data=f"pick::{opt}")] for opt in options]
    )

def registration_summary_phone(reg: Registration) -> str:
    """Summary text showing phone instead of topics/self_desc (phone stored in reg.topics)."""
    ulink = f"@{reg.telegram_username}" if reg.telegram_username else str(reg.telegram_id)
    phone = reg.topics or "—"
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
        f"{bold('📱 Qulay format')}: {reg.meet_format}\n"
        f"{bold('📞 Telefon')}: {phone}\n\n"
        f"{bold('Sana/vaqt')}: {reg.created_at} ({LOCAL_TZ})"
    )

def sanitize_phone(raw: str) -> str:
    # Keep + and digits only; trim spaces/dashes/parentheses
    cleaned = "".join(ch for ch in raw if (ch.isdigit() or ch == "+"))
    # Add + if it starts with 998 or 7 or 1 etc. and no + provided (optional)
    if cleaned and cleaned[0] != "+" and len(cleaned) >= 9:
        cleaned = "+" + cleaned
    return cleaned

# ---------------------- Handlers: Core Flow ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Salom! Finlit Networking ro‘yxatdan o‘tish uchun quyidagi savollarga javob bering.\n\n"
        "Boshlaymiz. Avvalo, 👤 Ismingiz va familiyangizni yuboring:"
    )
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
        await q.edit_message_reply_markup(
            make_multiselect_kb(LANGUAGE_OPTIONS, selected, with_done=True, with_text_alt=True)
        )
        return LANGUAGES
    elif data == "alt::text":
        await q.message.reply_text("✍️ Qaysi boshqa tillar? Matn ko‘rinishida yozing (masalan: Nemischa, Turkcha).")
        return LANGUAGES_TEXT
    elif data == "done::ok":
        if not selected and not context.user_data.get("languages_text"):
            await q.message.reply_text("Iltimos, kamida bitta tilni tanlang yoki yozib yuboring.")
            return LANGUAGES
        # Go to format next
        kb = make_singleselect_kb(FORMAT_OPTIONS)
        await q.message.reply_text("📱 Sizga qaysi format qulayroq:", reply_markup=kb)
        return MEET_FORMAT

async def languages_text_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["languages_text"] = update.message.text.strip()
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
        # Ask for phone number, allow contact share
        kb = ReplyKeyboardMarkup(
            [[KeyboardButton("📞 Raqamni ulashish", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await q.message.reply_text(
            "📞 Telefon raqamingizni yuboring (matn ko‘rinishida yoki tugma orqali ulashishingiz mumkin):",
            reply_markup=kb,
        )
        return PHONE

async def on_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Accept contact or plain text
    phone = None
    if update.message and update.message.contact and update.message.contact.phone_number:
        phone = update.message.contact.phone_number
    elif update.message and update.message.text:
        phone = update.message.text.strip()

    phone = sanitize_phone(phone or "")
    if not phone or len(phone) < 7:
        await update.message.reply_text(
            "❗️ Iltimos, to‘g‘ri telefon raqamini kiriting yoki tugma orqali ulashingiz mumkin."
        )
        return PHONE

    # Map phone into 'topics' field for compatibility; no self_desc used.
    context.user_data["topics"] = phone
    context.user_data["self_desc"] = ""

    # Build, save, export, notify
    reg = Registration.from_context(context, update)
    reg.save()
    try:
        export_to_excel(EXCEL_PATH)
    except Exception as e:
        log.warning("Excel export failed: %s", e)

    # Clear custom keyboard
    await update.message.reply_text(
        "✅ Ro‘yxatdan o‘tish tugadi!\n\n" + registration_summary_phone(reg),
        parse_mode=ParseMode.HTML,
        reply_markup=None,
    )

    # DM organizers
    for admin_id in ORGANIZER_IDS:
        try:
            await update.message.get_bot().send_message(
                chat_id=admin_id,
                text=registration_summary_phone(reg),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.warning("Failed to DM organizer %s: %s", admin_id, e)

    return ConversationHandler.END

# ---------------------- Handlers: Admin & Utility ----------------------
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"Sizning user id: {u.id}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = "\n".join([
        "Buyruqlar:",
        "/start — ro‘yxatdan o‘tishni boshlash",
        "/whoami — user id ni ko‘rsatish",
        "/stats — (admin) registratsiyalar statistikasi",
        "/export_excel — (admin) Excel faylni yuborish",
    ])
    await update.message.reply_text(txt)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")

    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM registrations")
        total = cur.fetchone()[0]
        cur.execute("SELECT created_at FROM registrations")
        rows = [r[0] for r in cur.fetchall()]

    now = datetime.now(TZ)
    today = now.date()
    start_of_week = (now - timedelta(days=now.weekday())).date()

    today_count = 0
    week_count = 0
    for v in rows:
        if isinstance(v, datetime):
            d = v.date()
        else:
            try:
                d = datetime.strptime(str(v), "%Y-%m-%d %H:%M:%S").date()
            except Exception:
                try:
                    d = datetime.fromisoformat(str(v)).date()
                except Exception:
                    continue
        if d == today:
            today_count += 1
        if d >= start_of_week:
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
        await update.message.reply_document(
            document=Path(path).open('rb'),
            filename=Path(EXCEL_PATH).name,
            caption="Registratsiyalar (Excel)"
        )
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
            MEET_FORMAT: [CallbackQueryHandler(on_format_cb)],
            PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), on_phone)],
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
