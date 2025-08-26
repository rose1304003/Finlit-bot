# -*- coding: utf-8 -*-
"""
Finlit Networking – Registration Bot (MySQL storage)

- Stores registrations in MySQL (env vars: MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB)
- Also exports to Excel (data/registrations.xlsx)
- Sends summary to participants + organizers (ORGANIZER_IDS)
"""

from __future__ import annotations
import os
import logging
import mysql.connector
import pandas as pd
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Set

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
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

def parse_admins(raw: str | None) -> List[int]:
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

ORGANIZER_IDS: List[int] = parse_admins(os.getenv("ORGANIZER_IDS"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("finlit-bot")

# ---------------------- DB Layer (MySQL) ----------------------
def db_connect():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DB", "finlit"),
        charset="utf8mb4"
    )

def ensure_db():
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            telegram_id BIGINT,
            telegram_username VARCHAR(255),
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
            created_at DATETIME
        )
        """)
        conn.commit()

@dataclass
class Registration:
    telegram_id: int
    telegram_username: str | None
    full_name: str
    workplace: str
    career_field: str
    interests: str
    networking_goals: str
    region: str
    languages: str
    topics: str
    meet_format: str
    self_desc: str
    created_at: str

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

    def save(self):
        with db_connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO registrations (
                    telegram_id, telegram_username, full_name, workplace,
                    career_field, interests, networking_goals, region, languages,
                    topics, meet_format, self_desc, created_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                self.telegram_id, self.telegram_username, self.full_name, self.workplace,
                self.career_field, self.interests, self.networking_goals, self.region,
                self.languages, self.topics, self.meet_format, self.self_desc, self.created_at
            ))
            conn.commit()

def export_to_excel(path: str | Path = EXCEL_PATH) -> Path:
    with db_connect() as conn:
        df = pd.read_sql("SELECT * FROM registrations ORDER BY id DESC", conn)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
    return path

# ---------------------- Helpers ----------------------
NETWORKING_OPTIONS = ["Yangi tanishlar", "Hamkorlik imkoniyatlari", "Tajriba almashish", "Ilhom va g‘oyalar"]
LANGUAGE_OPTIONS = ["O‘zbekcha", "Ruscha", "Inglizcha"]
FORMAT_OPTIONS = ["Oflayn uchrashuv", "Onlayn format", "Gibrid"]

(NAME, WORKPLACE, CAREER, INTERESTS, NETWORKING, REGION,
 LANGUAGES, LANGUAGES_TEXT, TOPICS, MEET_FORMAT, SELF_DESC, CONFIRM) = range(12)

def is_admin(user_id: int) -> bool: return user_id in ORGANIZER_IDS
def bold(s: str) -> str: return f"<b>{s}</b>"

# ---------------------- Handlers ----------------------
# (reuse your existing ask_* and on_* conversation handlers from previous version)
# (no change needed, only DB logic above is different)

# ---------------------- Main ----------------------
def build_app() -> Application:
    ensure_db()
    app = Application.builder().token(BOT_TOKEN).build()
    # add ConversationHandler and commands as before
    return app

def main():
    app = build_app()
    log.info("Finlit Registration Bot started. Organizers: %s", ORGANIZER_IDS)
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
