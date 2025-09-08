# -*- coding: utf-8 -*-
"""
Finlit Networking – Registration Bot (DM-only, no DB)
Adds:
• Thank-you message after successful registration
• File-based registry of registered user IDs (data/registered.json)
• Admin commands:
    /broadcast <text>    → DM to all registered users
    /registered_count    → how many registered

Env (.env / Railway Variables)
  TELEGRAM_BOT_TOKEN=123456:AA...
  ORGANIZER_IDS=111111111,222222222
  LOCAL_TZ=Asia/Tashkent                 (optional)
  REG_DB_PATH=data/registered.json       (optional; default as shown)
"""

from __future__ import annotations
import os
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Set

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# ---------------------- Config ----------------------
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")

LOCAL_TZ = os.getenv("LOCAL_TZ", "Asia/Tashkent")
TZ = ZoneInfo(LOCAL_TZ)

# Where we store registered user IDs (flat JSON file)
REG_DB_PATH = Path(os.getenv("REG_DB_PATH", "data/registered.json"))
REG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def parse_admins(raw: str | None) -> List[int]:
    if not raw:
        return []
    out: List[int] = []
    for p in raw.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            pass
    return out

ORGANIZER_IDS: List[int] = parse_admins(os.getenv("ORGANIZER_IDS"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("finlit-bot")

# ---------------------- Tiny registry (file-based) ----------------------
def _load_registered_ids() -> Set[int]:
    if not REG_DB_PATH.exists():
        return set()
    try:
        data = json.loads(REG_DB_PATH.read_text(encoding="utf-8"))
        return set(int(x) for x in data)
    except Exception:
        return set()

def _save_registered_ids(ids: Set[int]) -> None:
    REG_DB_PATH.write_text(json.dumps(sorted(list(ids))), encoding="utf-8")

def add_registered_user(user_id: int) -> None:
    ids = _load_registered_ids()
    if user_id not in ids:
        ids.add(user_id)
        _save_registered_ids(ids)

# ---------------------- Conversation options ----------------------
NETWORKING_OPTIONS = [
    "Men rezidentman",
    "Men tomoshabinman",
]
LANGUAGE_OPTIONS = ["O‘zbekcha", "Ruscha", "Inglizcha"]
FORMAT_OPTIONS   = ["Oflayn uchrashuv", "Onlayn format", "Gibrid"]

# Conversation states
(NAME, WORKPLACE, CAREER, INTERESTS, NETWORKING, REGION,
 LANGUAGES, LANGUAGES_TEXT, MEET_FORMAT, PHONE) = range(10)

# ---------------------- Helpers ----------------------
def bold(s: str) -> str:
    return f"<b>{s}</b>"

def make_multiselect_kb(
    options: List[str], selected: Set[str], with_done: bool = True, with_text_alt: bool = False
) -> InlineKeyboardMarkup:
    rows = []
    for opt in options:
        mark = "☑️" if opt in selected else "⬜️"
        rows.append([InlineKeyboardButton(f"{mark} {opt}", callback_data=f"opt::{opt}")])
    extra = []
    if with_text_alt:
        extra.append(InlineKeyboardButton("✍️ Boshqa (yozib kiriting)", callback_data="alt::text"))
    if with_done:
        extra.append(InlineKeyboardButton("✅ Tayyor", callback_data="done::ok"))
    if extra:
        rows.append(extra)
    return InlineKeyboardMarkup(rows)

def make_singleselect_kb(options: List[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=f"pick::{opt}")] for opt in options])

def sanitize_phone(raw: str | None) -> str:
    raw = raw or ""
    cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if cleaned and cleaned[0] != "+" and len(cleaned) >= 9:
        cleaned = "+" + cleaned
    return cleaned

def build_summary(data: dict, user) -> str:
    networking = ", ".join(sorted(data.get("networking_selected", set())))
    langs = ", ".join(sorted(data.get("languages_selected", set()))
                      + ([data.get("languages_text")] if data.get("languages_text") else []))
    phone = data.get("phone", "—")
    now_local = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    ulink = f"@{user.username}" if user.username else str(user.id)
    return (
        f"✅ {bold('Yangi ro‘yxatdan o‘tish!')}\n"
        f"{bold('Foydalanuvchi')}: {ulink}\n\n"
        f"{bold('👤 Ism-familiya')}: {data.get('full_name','')}\n"
        f"{bold('🏢 Ish/o‘qish joyi')}: {data.get('workplace','')}\n"
        f"{bold('💼 Kasbiy yo‘nalish')}: {data.get('career_field','')}\n"
        f"{bold('📊 Qiziq sohalar')}: {data.get('interests','')}\n"
        f"{bold('🤝 Networking maqsadi')}: {networking}\n"
        f"{bold('🌍 Hudud')}: {data.get('region','')}\n"
        f"{bold('🗣 Tillar')}: {langs}\n"
        f"{bold('📱 Qulay format')}: {data.get('meet_format','')}\n"
        f"{bold('📞 Telefon')}: {phone}\n\n"
        f"{bold('Sana/vaqt')}: {now_local} ({LOCAL_TZ})"
    )

# ---------------------- Flow ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Salom! Finlit Networking ro‘yxatdan o‘tish uchun quyidagi savollarga javob bering.\n\n"
        "Boshlaymiz. Avvalo, 👤 ismingiz va familiyangizni yuboring:"
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
    kb = make_multiselect_kb(NETWORKING_OPTIONS, set(), with_done=True)
    await update.message.reply_text(
        "🤝 Networkingdan qanday maqsadda qatnashmoqchisiz? Bir nechta bandni tanlang:",
        reply_markup=kb
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
        await q.edit_message_reply_markup(make_multiselect_kb(NETWORKING_OPTIONS, selected, with_done=True))
        return NETWORKING
    elif data == "done::ok":
        if not selected:
            await q.message.reply_text("Kamida bitta maqsadni tanlang, iltimos.")
            return NETWORKING
        await q.message.reply_text("🌍 Qaysi hududdan qatnashyapsiz?")
        return REGION

async def ask_languages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["region"] = update.message.text.strip()
    context.user_data["languages_selected"] = set()
    kb = make_multiselect_kb(LANGUAGE_OPTIONS, set(), with_done=True, with_text_alt=True)
    await update.message.reply_text(
        "🗣 Qaysi tillarda muloqot qilish qulay? Bir nechta bandni tanlang yoki “Boshqa” ni bosing.",
        reply_markup=kb
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
    if q.data.startswith("pick::"):
        context.user_data["meet_format"] = q.data.split("::", 1)[1]
        kb = ReplyKeyboardMarkup(
            [[KeyboardButton("📞 Raqamni ulashish", request_contact=True)]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await q.message.reply_text(
            "📞 Telefon raqamingizni yuboring (matn ko‘rinishida yoki tugma orqali ulashishingiz mumkin):",
            reply_markup=kb
        )
        return PHONE

async def on_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = None
    if update.message.contact and update.message.contact.phone_number:
        phone = update.message.contact.phone_number
    else:
        phone = (update.message.text or "").strip()
    phone = sanitize_phone(phone)
    if not phone or len(phone) < 7:
        await update.message.reply_text("❗️ Iltimos, to‘g‘ri telefon raqamini kiriting yoki tugma orqali ulashingiz mumkin.")
        return PHONE

    context.user_data["phone"] = phone

    # Build summary and thank-you
    summary = build_summary(context.user_data, update.effective_user)
    thanks = (
        "🎉 Rahmat! Ro‘yxatdan o‘tish muvaffaqiyatli yakunlandi.\n"
        "Tez orada tafsilotlarni ulashamiz. Savollar bo‘lsa — shu yerda yozishingiz mumkin."
    )

    # Send to user
    await update.message.reply_text("✅ Ro‘yxatdan o‘tish tugadi!\n\n" + summary, parse_mode=ParseMode.HTML)
    await update.message.reply_text(thanks)

    # Track as registered (for future broadcasts)
    add_registered_user(update.effective_user.id)

    # DM organizers/owner(s)
    for admin_id in ORGANIZER_IDS:
        try:
            await update.message.get_bot().send_message(chat_id=admin_id, text=summary, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.warning("Failed to DM organizer %s: %s", admin_id, e)

    return ConversationHandler.END

# ---------------------- Admin Commands ----------------------
def _is_admin(user_id: int) -> bool:
    return user_id in ORGANIZER_IDS

async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Sizning user id: {update.effective_user.id}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Buyruqlar:\n"
        "/start — ro‘yxatdan o‘tishni boshlash\n"
        "/whoami — user id ni ko‘rsatish\n"
        "/registered_count — ro‘yxatdan o‘tganlar soni (admin)\n"
        "/broadcast <matn> — ro‘yxatdan o‘tganlarga xabar yuborish (admin)\n"
        "/cancel — bekor qilish"
    )

async def registered_count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")
    count = len(_load_registered_ids())
    await update.message.reply_text(f"📊 Ro‘yxatdan o‘tganlar soni: {count}")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return await update.message.reply_text("Bu buyruq faqat adminlar uchun.")

    # Get message text: either argument after command, or the text of a replied message
    text = update.message.text.partition(" ")[2].strip()
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text or ""
    if not text:
        return await update.message.reply_text("Foydalanish: /broadcast Matn... (yoki xabarga reply qilib /broadcast)")

    ids = sorted(_load_registered_ids())
    if not ids:
        return await update.message.reply_text("Ro‘yxatdan o‘tgan foydalanuvchilar ro‘yxati bo‘sh.")

    ok = 0
    fail = 0
    for uid in ids:
        try:
            await update.message.get_bot().send_message(chat_id=uid, text=text)
            ok += 1
            time.sleep(0.05)  # small delay to be nice to Telegram
        except Exception:
            fail += 1
    await update.message.reply_text(f"Yuborildi: {ok}, Xato: {fail}")

# ---------------------- Cancel / Fallback ----------------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi. /start orqali qayta boshlashingiz mumkin.")
    return ConversationHandler.END

# ---------------------- App ----------------------
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME:          [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_workplace)],
            WORKPLACE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_career)],
            CAREER:        [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_interests)],
            INTERESTS:     [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_networking)],
            NETWORKING:    [CallbackQueryHandler(on_networking_cb)],
            REGION:        [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_languages)],
            LANGUAGES:     [CallbackQueryHandler(on_languages_cb)],
            LANGUAGES_TEXT:[MessageHandler(filters.TEXT & ~filters.COMMAND, languages_text_done)],
            MEET_FORMAT:   [CallbackQueryHandler(on_format_cb)],
            PHONE:         [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), on_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("registered_count", registered_count_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    return app

def main():
    log.info("Finlit Registration Bot (DM-only) starting… Owners: %s", ORGANIZER_IDS)
    app = build_app()
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
