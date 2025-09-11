# -*- coding: utf-8 -*-
"""
Finlit Networking – Registration Bot (UZ/RU language choice, file-based registry)
"""

import os, json, logging, time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Set, List
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
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
LOCAL_TZ = os.getenv("LOCAL_TZ", "Asia/Tashkent")
TZ = ZoneInfo(LOCAL_TZ)
REG_DB_PATH = Path(os.getenv("REG_DB_PATH", "data/registered.json"))
REG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def parse_admins(raw: str | None) -> List[int]:
    if not raw: return []
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]

ORGANIZER_IDS = parse_admins(os.getenv("ORGANIZER_IDS"))
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("finlit-bot")

# ---------------- Registry ----------------
def _load_registered_ids() -> Set[int]:
    if not REG_DB_PATH.exists(): return set()
    try:
        return set(json.loads(REG_DB_PATH.read_text()))
    except: return set()

def _save_registered_ids(ids: Set[int]) -> None:
    REG_DB_PATH.write_text(json.dumps(sorted(list(ids))), encoding="utf-8")

def add_registered_user(uid: int) -> None:
    ids = _load_registered_ids()
    ids.add(uid)
    _save_registered_ids(ids)

# ---------------- States ----------------
(LANG, NAME, BIRTH, PURPOSE, PHONE) = range(5)

def t(lang, key):
    texts = {
        "start": {
            "uz": "👋 Salom! Finlit Networking ro‘yxatdan o‘tish uchun quyidagi savollarga javob bering.\n\nMuloqot tilini tanlang:",
            "ru": "👋 Здравствуйте! Ответьте на следующие вопросы, чтобы зарегистрироваться в Finlit Networking.\n\nВыберите язык:"
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
        }
    }
    return texts[key][lang]

# ---------------- Flow ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("UZ", callback_data="lang:uz"),
         InlineKeyboardButton("RU", callback_data="lang:ru")]
    ])
    await update.message.reply_text(t("uz","start")+"\n"+t("ru","start"), reply_markup=kb)
    return LANG

async def on_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    lang = q.data.split(":")[1]
    context.user_data["lang"] = lang
    await q.message.reply_text(t(lang,"name"))
    return NAME

async def on_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(t(context.user_data["lang"], "birth"))
    return BIRTH

async def on_birth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["birth"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Rezident / Резидент", callback_data="purpose:rezident")],
        [InlineKeyboardButton("Tomoshabin / Зритель", callback_data="purpose:tomoshabin")]
    ])
    await update.message.reply_text(t(context.user_data["lang"], "purpose"), reply_markup=kb)
    return PURPOSE

async def on_purpose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["purpose"] = q.data.split(":")[1]
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📞 Share / Поделиться", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await q.message.reply_text(t(context.user_data["lang"], "phone"), reply_markup=kb)
    return PHONE

async def on_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.contact.phone_number if update.message.contact else update.message.text
    context.user_data["phone"] = phone
    lang = context.user_data["lang"]

    summary = f"""
👤 {context.user_data['name']}
📅 {context.user_data['birth']}
🤝 {context.user_data['purpose']}
📞 {phone}
"""
    await update.message.reply_text(summary, parse_mode=ParseMode.HTML)
    await update.message.reply_text(t(lang,"done"))

    add_registered_user(update.effective_user.id)
    for admin_id in ORGANIZER_IDS:
        try:
            await update.message.get_bot().send_message(chat_id=admin_id, text=summary)
        except Exception as e:
            log.warning("Failed DM admin: %s", e)

    return ConversationHandler.END

# ---------------- App ----------------
def build_app():
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANG: [CallbackQueryHandler(on_lang)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_name)],
            BIRTH:[MessageHandler(filters.TEXT & ~filters.COMMAND, on_birth)],
            PURPOSE:[CallbackQueryHandler(on_purpose)],
            PHONE:[MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), on_phone)]
        },
        fallbacks=[]
    )
    app.add_handler(conv)
    return app

def main():
    app = build_app()
    app.run_polling()

if __name__ == "__main__":
    main()
