# -*- coding: utf-8 -*-
"""
Finlit Networking – Registration Bot (UZ/RU; file-based registry; admin stats)

Features:
• Language choice (UZ/RU)
• Registration flow: name → birthdate → purpose (Rezident/Tomoshabin) → phone
• Thank-you message + summary
• File-based registry (JSON) with structured records:
    { id, purpose, ts, name, birth, phone, lang }
• Admin-only DMs on each registration (to ORGANIZER_IDS only)
• Admin commands:
    /whoami                    → shows your Telegram user id
    /registered_count          → number of registered users (unique ids)
    /daily_stats               → yesterday's registrations by purpose (local TZ)
    /broadcast <text>          → DM text to all registered users (admins only)

Env (.env / Railway Variables)
  TELEGRAM_BOT_TOKEN=123456:AA...
  ORGANIZER_IDS=111111111,222222222
  LOCAL_TZ=Asia/Tashkent                 (optional, default as shown)
  REG_DB_PATH=data/registered.json       (optional, default as shown)

Notes:
• If you previously used a version that stored just a list of IDs, this version
  will start writing structured records. Old entries without timestamps/purpose
  cannot be used for daily breakdowns unless you migrate them manually.
"""

from __future__ import annotations

import os
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from typing import Set, List, Dict, Any

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters
)

# ---------------- Config ----------------
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment.")

LOCAL_TZ = os.getenv("LOCAL_TZ", "Asia/Tashkent")
TZ = ZoneInfo(LOCAL_TZ)
REG_DB_PATH = Path(os.getenv("REG_DB_PATH", "data/registered.json"))
REG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def parse_admins(raw: str | None) -> List[int]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    ids: List[int] = []
    for p in parts:
        try:
            ids.append(int(p))
        except ValueError:
            pass
    return ids

ORGANIZER_IDS: List[int] = parse_admins(os.getenv("ORGANIZER_IDS"))
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("finlit-bot")

# ---------------- Texts ----------------
def t(lang: str, key: str) -> str:
    texts = {
        "start": {
            "uz": "👋 Salom! Finlit Networking ro‘yxatdan o‘tish uchun quyidagi savollarga javob bering.\n\n👉 Muloqot tilini tanlang:",
            "ru": "👋 Здравствуйте! Ответьте на следующие вопросы, чтобы зарегистрироваться в Finlit Networking.\n\n👉 Выберите язык:"
        },
        "name": {
            "uz": "Boshlaymiz. Avvalo, 👤 ismingiz va familiyangizni yuboring:",
            "ru": "Давайте начнём. Для начала отправьте своё имя и фамилию:"
        },
        "birth": {
            "uz": "📅 Tug‘ilgan sana (misol: 01/01/2001):",
            "ru": "📅 Дата рождения (например, 01.01.2001):"
        },
        "purpose": {
            "uz": "🤝 Networkingdan qanday maqsadda qatnashmoqchisiz?",
            "ru": "🤝 Какова цель вашего общения?"
        },
        "phone": {
            "uz": "📞 Telefon raqamingizni yuboring (matn ko‘rinishida yoki tugma orqali ulashishingiz mumkin):",
            "ru": "📞 Отправьте свой номер телефона (в текстовом сообщении или с помощью кнопки):"
        },
        "done": {
            "uz": "🎉 Rahmat! Ro‘yxatdan o‘tish muvaffaqiyatli yakunlandi!",
            "ru": "🎉 Спасибо! Регистрация успешно завершена!"
        },
        "admins_only": {
            "uz": "Bu buyruq faqat adminlar uchun.",
            "ru": "Эта команда доступна только администраторам."
        },
        "nobody": {
            "uz": "Hech kim ro‘yxatdan o‘tmagan hali.",
            "ru": "Пока никто не зарегистрировался."
        }
    }
    return texts[key][lang if lang in ("uz", "ru") else "uz"]

# ---------------- Registry ----------------
def _load_registry() -> List[Dict[str, Any]]:
    """Read registry as list of structured records."""
    if not REG_DB_PATH.exists():
        return []
    try:
        data = json.loads(REG_DB_PATH.read_text(encoding="utf-8"))
        # If old format (list of ints), keep but ignore for stats.
        if isinstance(data, list) and data and isinstance(data[0], int):
            # Convert to minimal records without ts/purpose (not used for daily stats)
            return [{"id": int(x)} for x in data]
        # If already structured or empty, return as-is
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        log.warning("Failed to read registry: %s", e)
        return []

def _save_registry(reg: List[Dict[str, Any]]) -> None:
    REG_DB_PATH.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")

def _unique_ids(reg: List[Dict[str, Any]]) -> Set[int]:
    ids: Set[int] = set()
    for r in reg:
        try:
            ids.add(int(r["id"]))
        except Exception:
            continue
    return ids

def add_registered_user(
    uid: int,
    purpose: str,
    name: str,
    birth: str,
    phone: str,
    lang: str
) -> None:
    """Append structured record if user not yet present."""
    reg = _load_registry()
    if any((str(r.get("id")) == str(uid)) for r in reg):
        return
    rec = {
        "id": uid,
        "purpose": purpose,          # "rezident" | "tomoshabin"
        "ts": datetime.now(TZ).isoformat(),
        "name": name,
        "birth": birth,
        "phone": phone,
        "lang": lang
    }
    reg.append(rec)
    _save_registry(reg)

# ---------------- States ----------------
(LANG, NAME, BIRTH, PURPOSE, PHONE) = range(5)

# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("UZ", callback_data="lang:uz"),
         InlineKeyboardButton("RU", callback_data="lang:ru")]
    ])
    # Show both language intros together to avoid blank start in some clients
    await update.message.reply_text(
        f"{t('uz','start')}\n\n{t('ru','start')}",
        reply_markup=kb
    )
    return LANG

async def on_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = q.data.split(":")[1]
    context.user_data["lang"] = lang
    await q.message.reply_text(t(lang, "name"))
    return NAME

async def on_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = (update.message.text or "").strip()
    await update.message.reply_text(t(context.user_data.get("lang", "uz"), "birth"))
    return BIRTH

async def on_birth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["birth"] = (update.message.text or "").strip()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Rezident / Резидент", callback_data="purpose:rezident")],
        [InlineKeyboardButton("Speeker / Speeker", callback_data="purpose:tomoshabin")]
    ])
    await update.message.reply_text(
        t(context.user_data.get("lang", "uz"), "purpose"),
        reply_markup=kb
    )
    return PURPOSE

async def on_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    purpose = q.data.split(":")[1]
    context.user_data["purpose"] = purpose
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📞 Share / Поделиться", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await q.message.reply_text(
        t(context.user_data.get("lang", "uz"), "phone"),
        reply_markup=kb
    )
    return PHONE

async def on_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Normalize phone from contact or text
    phone = ""
    if update.message and update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = (update.message.text or "").strip()

    lang = context.user_data.get("lang", "uz")
    name = context.user_data.get("name", "")
    birth = context.user_data.get("birth", "")
    purpose = context.user_data.get("purpose", "")

    # Save registry (structured)
    add_registered_user(
        uid=update.effective_user.id,
        purpose=purpose,
        name=name,
        birth=birth,
        phone=phone,
        lang=lang
    )

    # Build summary
    purpose_h = {
        "rezident": "Rezident / Резидент",
        "tomoshabin": "Tomoshabin / Зритель"
    }.get(purpose, purpose)

    summary = (
        f"👤 {name}\n"
        f"📅 {birth}\n"
        f"🤝 {purpose_h}\n"
        f"📞 {phone}\n"
        f"🆔 {update.effective_user.id}"
    )

    # Thank-you and echo summary to the user (remove contact keyboard)
    await update.message.reply_text("✅ " + t(lang, "done"), parse_mode=ParseMode.HTML,
                                    reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text(summary)

    # DM admins only (never to regular users)
    for admin_id in ORGANIZER_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text="🆕 Yangi ro‘yxatga olish:\n" + summary)
        except Exception as e:
            log.warning("Failed DM to admin %s: %s", admin_id, e)

    return ConversationHandler.END

# ---------------- Admin Helpers ----------------
def _is_admin(user_id: int) -> bool:
    return int(user_id) in set(ORGANIZER_IDS)

# ---------------- Admin Commands ----------------
async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Sizning user id: {update.effective_user.id}")

async def registered_count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = "uz"
    if update and update.effective_user:
        # Try to honor user's last chosen lang if present in memory
        lang = context.user_data.get("lang", "uz")
    if not _is_admin(update.effective_user.id):
        return await update.message.reply_text(t(lang, "admins_only"))

    reg = _load_registry()
    count = len(_unique_ids(reg))
    await update.message.reply_text(f"📊 Ro‘yxatdan o‘tganlar soni: {count}")

async def daily_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "uz")
    if not _is_admin(update.effective_user.id):
        return await update.message.reply_text(t(lang, "admins_only"))

    reg = _load_registry()
    if not reg:
        return await update.message.reply_text(t(lang, "nobody"))

    today: date = datetime.now(TZ).date()
    yesterday: date = today - timedelta(days=1)

    rez = tomo = 0
    for r in reg:
        ts_str = r.get("ts")
        purpose = r.get("purpose")
        if not ts_str or not purpose:
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
            # If ts is naive, localize; else convert
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ)
            ts_d = ts.astimezone(TZ).date()
        except Exception:
            continue

        if ts_d == yesterday:
            if purpose == "rezident":
                rez += 1
            elif purpose == "tomoshabin":
                tomo += 1

    total = rez + tomo
    msg = (
        f"📊 Kecha ({yesterday.isoformat()}) natijalar:\n"
        f"• Rezidentlar: {rez}\n"
        f"• Tomoshabinlar: {tomo}\n"
        f"• Jami: {total}"
    )
    await update.message.reply_text(msg)

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "uz")
    if not _is_admin(update.effective_user.id):
        return await update.message.reply_text(t(lang, "admins_only"))

    text = update.message.text.partition(" ")[2].strip()
    if not text:
        return await update.message.reply_text("Foydalanish: /broadcast <xabar matni>")

    reg = _load_registry()
    ids = sorted(_unique_ids(reg))
    ok = fail = 0
    for uid in ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            ok += 1
            await asyncio.sleep(0.05)  # non-blocking pause
        except Exception:
            fail += 1
    await update.message.reply_text(f"Yuborildi: {ok}, Xato: {fail}")

# ---------------- App ----------------
def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANG: [CallbackQueryHandler(on_lang)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_name)],
            BIRTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_birth)],
            PURPOSE: [CallbackQueryHandler(on_purpose)],
            PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), on_phone)]
        },
        fallbacks=[],
        name="finlit_registration",
        persistent=False,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("registered_count", registered_count_cmd))
    app.add_handler(CommandHandler("daily_stats", daily_stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    return app

def main():
    log.info("Finlit Registration Bot starting… Admins: %s | TZ: %s | DB: %s",
             ORGANIZER_IDS, LOCAL_TZ, str(REG_DB_PATH))
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
