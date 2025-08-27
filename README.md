# -*- coding: utf-8 -*-

"""
Finlit Networking – Registration Bot (MySQL storage via storage.py)

Features

* Step-by-step registration (Uzbek Latin prompts)
* Multi-select for Networking goals and Languages (inline buttons)
* Single-select for preferred format (inline buttons)
* Saves registrations in MySQL (see storage.py)
* Auto-exports/updates Excel (data/registrations.xlsx)
* DMs every completed registration to ORGANIZER\_IDS
* Admin commands: /stats, /export\_excel, /whoami, /help

Run
python finlit\_registration\_bot.py
"""
from **future** import annotations
import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Set

from dotenv import load\_dotenv
from telegram import (
Update,
InlineKeyboardMarkup,
InlineKeyboardButton,
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

# Make sure storage.py (the MySQL version) is in the same folder.

from storage import ensure\_db, Registration, export\_to\_excel, db\_connect

# ---------------------- Setup & Config ----------------------

load\_dotenv()
BOT\_TOKEN = os.getenv("TELEGRAM\_BOT\_TOKEN")
if not BOT\_TOKEN:
raise SystemExit("Missing TELEGRAM\_BOT\_TOKEN in environment.")

LOCAL\_TZ = os.getenv("LOCAL\_TZ", "Asia/Tashkent")
TZ = ZoneInfo(LOCAL\_TZ)

EXCEL\_PATH = os.getenv("EXCEL\_PATH", "data/registrations.xlsx")

def parse\_admins(raw: str | None) -> List\[int]:
if not raw:
return \[]
ids: List\[int] = \[]
for part in raw\.split(','):
part = part.strip()
if part:
try:
ids.append(int(part))
except ValueError:
pass
return ids

ORGANIZER\_IDS: List\[int] = parse\_admins(os.getenv("ORGANIZER\_IDS"))

logging.basicConfig(
level=logging.INFO,
format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("finlit-bot")

# ---------------------- Helpers ----------------------

NETWORKING\_OPTIONS = \[
"Yangi tanishlar",
"Hamkorlik imkoniyatlari",
"Tajriba almashish",
"Ilhom va g‘oyalar",
]

LANGUAGE\_OPTIONS = \[
"O‘zbekcha",
"Ruscha",
"Inglizcha",
]

FORMAT\_OPTIONS = \[
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
LANGUAGES\_TEXT,
TOPICS,
MEET\_FORMAT,
SELF\_DESC,
CONFIRM,
) = range(12)

def is\_admin(user\_id: int) -> bool:
return user\_id in ORGANIZER\_IDS

def bold(s: str) -> str:
return f"<b>{s}</b>"

def make\_multiselect\_kb(options: List\[str], selected: Set\[str], with\_done: bool = True, with\_text\_alt: bool = False) -> InlineKeyboardMarkup:
rows = \[]
for opt in options:
mark = "☑️" if opt in selected else "⬜️"
rows.append(\[InlineKeyboardButton(text=f"{mark} {opt}", callback\_data=f"opt::{opt}")])
extra = \[]
if with\_text\_alt:
extra.append(InlineKeyboardButton("✍️ Boshqa (yozib kiriting)", callback\_data="alt::text"))
if with\_done:
extra.append(InlineKeyboardButton("✅ Tayyor", callback\_data="done::ok"))
if extra:
rows.append(extra)
return InlineKeyboardMarkup(rows)

def make\_singleselect\_kb(options: List\[str]) -> InlineKeyboardMarkup:
rows = \[]
for opt in options:
rows.append(\[InlineKeyboardButton(text=opt, callback\_data=f"pick::{opt}")])
return InlineKeyboardMarkup(rows)

def registration\_summary(reg: Registration) -> str:
ulink = f"@{reg.telegram\_username}" if reg.telegram\_username else str(reg.telegram\_id)
return (
f"✅ {bold('Yangi ro‘yxatdan o‘tish!')}
"
f"{bold('Foydalanuvchi')}: {ulink}

"
f"{bold('👤 Ism-familiya')}: {reg.full\_name}
"
f"{bold('🏢 Ish/o‘qish joyi')}: {reg.workplace}
"
f"{bold('💼 Kasbiy yo‘nalish')}: {reg.career\_field}
"
f"{bold('📊 Qiziq sohalar')}: {reg.interests}
"
f"{bold('🤝 Networking maqsadi')}: {reg.networking\_goals}
"
f"{bold('🌍 Hudud')}: {reg.region}
"
f"{bold('🗣 Tillar')}: {reg.languages}
"
f"{bold('🚀 Qiziqqan mavzular')}: {reg.topics}
"
f"{bold('📱 Qulay format')}: {reg.meet\_format}
"
f"{bold('✨ Bir og‘izda')}: {reg.self\_desc}

"
f"{bold('Sana/vaqt')}: {reg.created\_at} ({LOCAL\_TZ})"
)

# ---------------------- Handlers: Core Flow ----------------------

async def start(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data.clear()
await update.message.reply\_text(
"👋 Salom! Finlit Networking ro‘yxatdan o‘tish uchun quyidagi savollarga javob bering.

"
"Boshlaymiz. Avvalo, "
"👤 Ismingiz va familiyangizni yuboring:")
return NAME

async def ask\_workplace(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data\["full\_name"] = update.message.text.strip()
await update.message.reply\_text("🏢 Qaerda ishlaysiz yoki o‘qiysiz? (tashkilot/universitet nomi)")
return WORKPLACE

async def ask\_career(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data\["workplace"] = update.message.text.strip()
await update.message.reply\_text("💼 Sizning kasbiy yo‘nalishingiz?")
return CAREER

async def ask\_interests(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data\["career\_field"] = update.message.text.strip()
await update.message.reply\_text("📊 Qaysi moliyaviy yoki iqtisodiy sohalar siz uchun eng qiziqarli?")
return INTERESTS

async def ask\_networking(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data\["interests"] = update.message.text.strip()
context.user\_data\["networking\_selected"] = set()
kb = make\_multiselect\_kb(NETWORKING\_OPTIONS, set(), with\_done=True, with\_text\_alt=False)
await update.message.reply\_text(
"🤝 Networkingdan qanday maqsadda qatnashmoqchisiz? Bir nechta bandni tanlashingiz mumkin:",
reply\_markup=kb,
)
return NETWORKING

async def on\_networking\_cb(update: Update, context: ContextTypes.DEFAULT\_TYPE):
q = update.callback\_query
await q.answer()
data = q.data
selected: Set\[str] = context.user\_data.get("networking\_selected", set())
if data.startswith("opt::"):
val = data.split("::", 1)\[1]
if val in selected:
selected.remove(val)
else:
selected.add(val)
context.user\_data\["networking\_selected"] = selected
await q.edit\_message\_reply\_markup(make\_multiselect\_kb(NETWORKING\_OPTIONS, selected))
return NETWORKING
elif data == "done::ok":
if not selected:
await q.reply\_text("Kamida bitta maqsadni tanlang, iltimos.")
return NETWORKING
await q.message.reply\_text("🌍 Qaysi hududdan qatnashyapsiz?")
return REGION

async def ask\_languages(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data\["region"] = update.message.text.strip()
context.user\_data\["languages\_selected"] = set()
kb = make\_multiselect\_kb(LANGUAGE\_OPTIONS, set(), with\_done=True, with\_text\_alt=True)
await update.message.reply\_text(
"🗣 Qaysi tillarda muloqot qilish qulay? Bir nechta bandni tanlang yoki "Boshqa" ni bosing.",
reply\_markup=kb,
)
return LANGUAGES

async def on\_languages\_cb(update: Update, context: ContextTypes.DEFAULT\_TYPE):
q = update.callback\_query
await q.answer()
data = q.data
selected: Set\[str] = context.user\_data.get("languages\_selected", set())
if data.startswith("opt::"):
val = data.split("::", 1)\[1]
if val in selected:
selected.remove(val)
else:
selected.add(val)
context.user\_data\["languages\_selected"] = selected
await q.edit\_message\_reply\_markup(make\_multiselect\_kb(LANGUAGE\_OPTIONS, selected, with\_done=True, with\_text\_alt=True))
return LANGUAGES
elif data == "alt::text":
await q.message.reply\_text("✍️ Qaysi boshqa tillar? Matn ko‘rinishida yozing (masalan: Nemischa, Turkcha).")
return LANGUAGES\_TEXT
elif data == "done::ok":
if not selected and not context.user\_data.get("languages\_text"):
await q.message.reply\_text("Iltimos, kamida bitta tilni tanlang yoki yozib yuboring.")
return LANGUAGES
await q.message.reply\_text("🚀 Finlit Networking davomida qaysi mavzular muhokama qilinishiga qiziqasiz?")
return TOPICS

async def languages\_text\_done(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data\["languages\_text"] = update.message.text.strip()
await update.message.reply\_text("🚀 Finlit Networking davomida qaysi mavzular muhokama qilinishiga qiziqasiz?")
return TOPICS

async def ask\_format(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data\["topics"] = update.message.text.strip()
kb = make\_singleselect\_kb(FORMAT\_OPTIONS)
await update.message.reply\_text("📱 Sizga qaysi format qulayroq:", reply\_markup=kb)
return MEET\_FORMAT

async def on\_format\_cb(update: Update, context: ContextTypes.DEFAULT\_TYPE):
q = update.callback\_query
await q.answer()
data = q.data
if data.startswith("pick::"):
picked = data.split("::", 1)\[1]
context.user\_data\["meet\_format"] = picked
await q.message.reply\_text("✨ Bir og‘izda o‘zingizni qanday ifoda etgan bo‘lardingiz? (Masalan: "Men – ...")")
return SELF\_DESC

async def confirm(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data\["self\_desc"] = update.message.text.strip()
reg = Registration.from\_context(context, update)

```
text = (
    f"{bold('Tekshiring:')}
```

"
f"{bold('👤 Ism-familiya')}: {reg.full\_name}
"
f"{bold('🏢 Ish/o‘qish joyi')}: {reg.workplace}
"
f"{bold('💼 Kasbiy yo‘nalish')}: {reg.career\_field}
"
f"{bold('📊 Qiziq sohalar')}: {reg.interests}
"
f"{bold('🤝 Networking maqsadi')}: {reg.networking\_goals}
"
f"{bold('🌍 Hudud')}: {reg.region}
"
f"{bold('🗣 Tillar')}: {reg.languages}
"
f"{bold('🚀 Mavzular')}: {reg.topics}
"
f"{bold('📱 Format')}: {reg.meet\_format}
"
f"{bold('✨ Men –')}: {reg.self\_desc}

"
"Hammasi to‘g‘rimi?"
)
kb = InlineKeyboardMarkup(\[
\[InlineKeyboardButton("✅ Tasdiqlash", callback\_data="confirm::yes")],
\[InlineKeyboardButton("↩️ Qayta boshlash", callback\_data="confirm::restart")],
])
await update.message.reply\_text(text, reply\_markup=kb, parse\_mode=ParseMode.HTML)
return CONFIRM

async def on\_confirm\_cb(update: Update, context: ContextTypes.DEFAULT\_TYPE):
q = update.callback\_query
await q.answer()
data = q.data
if data == "confirm::restart":
context.user\_data.clear()
await q.message.reply\_text("Qaytadan boshlaymiz. 👤 Ismingiz va familiyangiz?")
return NAME
elif data == "confirm::yes":
reg = Registration.from\_context(context, update)
reg.save()
\# Export (update) Excel silently
try:
export\_to\_excel(EXCEL\_PATH)
except Exception as e:
log.warning("Excel export failed: %s", e)
\# Send receipts
user\_msg = "✅ Ro‘yxatdan o‘tish tugadi!

" + registration\_summary(reg)
await q.message.reply\_text(user\_msg, parse\_mode=ParseMode.HTML)
\# DM to organizers
for admin\_id in ORGANIZER\_IDS:
try:
await q.bot.send\_message(chat\_id=admin\_id, text=registration\_summary(reg), parse\_mode=ParseMode.HTML)
except Exception as e:
log.warning("Failed to DM organizer %s: %s", admin\_id, e)
return ConversationHandler.END

# ---------------------- Handlers: Admin & Utility ----------------------

async def whoami(update: Update, context: ContextTypes.DEFAULT\_TYPE):
u = update.effective\_user
await update.message.reply\_text(f"Sizning user id: {u.id}")

async def help\_cmd(update: Update, context: ContextTypes.DEFAULT\_TYPE):
txt = "
".join(\[
"Buyruqlar:",
"/start — ro‘yxatdan o‘tishni boshlash",
"/whoami — user id ni ko‘rsatish",
"/stats — (admin) registratsiyalar statistikasi",
"/export\_excel — (admin) Excel faylini yuborish",
])
await update.message.reply\_text(txt)

async def stats\_cmd(update: Update, context: ContextTypes.DEFAULT\_TYPE):
uid = update.effective\_user.id
if not is\_admin(uid):
return await update.message.reply\_text("Bu buyruq faqat adminlar uchun.")

```
# MySQL query for counts
with db_connect() as conn:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM registrations")
    total = cur.fetchone()[0]

    # get created_at values
    cur.execute("SELECT created_at FROM registrations")
    rows = [r[0] for r in cur.fetchall()]

now = datetime.now(TZ)
today = now.date()
start_of_week = (now - timedelta(days=now.weekday())).date()

today_count = 0
week_count = 0
for v in rows:
    # v may be a datetime or a string depending on connector
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
    f"📊 Statistikalar:
```

"
f"Jami: {total}
"
f"Bugun: {today\_count}
"
f"Ushbu hafta: {week\_count}"
)

async def export\_excel\_cmd(update: Update, context: ContextTypes.DEFAULT\_TYPE):
uid = update.effective\_user.id
if not is\_admin(uid):
return await update.message.reply\_text("Bu buyruq faqat adminlar uchun.")
path = export\_to\_excel(EXCEL\_PATH)
try:
await update.message.reply\_document(document=Path(path).open('rb'),
filename=Path(EXCEL\_PATH).name,
caption="Registratsiyalar (Excel)")
except Exception as e:
await update.message.reply\_text(f"Yuborishda xatolik: {e}")

# ---------------------- Cancel / Fallback ----------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT\_TYPE):
context.user\_data.clear()
await update.message.reply\_text("Bekor qilindi. /start orqali qayta boshlashingiz mumkin.")
return ConversationHandler.END

# ---------------------- Main ----------------------

def build\_app() -> Application:
ensure\_db()

```
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
```

def main():
app = build\_app()
log.info("Finlit Registration Bot started. Organizers: %s", ORGANIZER\_IDS)
app.run\_polling(close\_loop=False)

if **name** == "**main**":
main()
