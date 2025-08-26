# -*- coding: utf-8 -*-
"""
Storage layer for Finlit Registration Bot (MySQL)
Handles:
- Database connection (MySQL)
- Table creation
- Registration dataclass
- Excel export
"""

import os
import mysql.connector
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes

# ---------------------- Config ----------------------
LOCAL_TZ = os.getenv("LOCAL_TZ", "Asia/Tashkent")
TZ = ZoneInfo(LOCAL_TZ)

EXCEL_PATH = os.getenv("EXCEL_PATH", "data/registrations.xlsx")
DATA_DIR = Path(EXCEL_PATH).parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------- MySQL Connection ----------------------
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
    """Ensure the registrations table exists in MySQL"""
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

# ---------------------- Dataclass ----------------------
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
        """Insert registration into MySQL"""
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

# ---------------------- Excel Export ----------------------
def export_to_excel(path: str | Path = EXCEL_PATH) -> Path:
    """Export all registrations to Excel"""
    with db_connect() as conn:
        df = pd.read_sql("SELECT * FROM registrations ORDER BY id DESC", conn)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
    return path
