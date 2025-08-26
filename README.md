# Finlit Networking – Telegram Registration Bot

A production‑ready Telegram bot for event registration in Uzbek (Latin). It asks participants a step‑by‑step questionnaire, stores results in **SQLite**, continuously keeps an **Excel** file up to date, and DMs each completed registration to the organizers.

> **Repo one‑liner (description field):** Telegram bot for Finlit Networking registration — multi‑step form (UZ), SQLite + Excel export, admin stats, and organizer DM alerts.

---

## ✨ Features

* 📋 Guided, single/multi‑step registration in Uzbek (Latin)
* ✅ Multi‑select with inline buttons: **Networking goals**, **Languages**
* 🔘 Single‑select with inline buttons: **Preferred format** (Offline/Online/Hybrid)
* 💾 Data persistence: **SQLite** (`data/finlit.db`)
* 📊 Auto‑export to **Excel** on every successful registration (`data/registrations.xlsx`)
* 📥 Instant **DM** to all organizers for each submission
* 🔐 Admin commands: `/stats`, `/export_excel`, `/whoami`, `/help`
* 🕒 Timezone aware (defaults to `Asia/Tashkent`)

---

## 🧱 Tech Stack

* Python 3.10+
* [python-telegram-bot 21.x](https://docs.python-telegram-bot.org/)
* SQLite + pandas + openpyxl
* python-dotenv

---

## 📦 Project Structure

```
.
├─ finlit_registration_bot.py     # main single-file bot
├─ data/                          # DB + Excel are created here
│  ├─ finlit.db
│  └─ registrations.xlsx
├─ .env                           # secrets & config (not committed)
└─ requirements.txt               # pinned deps (optional)
```

**requirements.txt** (optional)

```
python-telegram-bot==21.4
pandas
openpyxl
python-dotenv
```

---

## ⚙️ Configuration

Create a file named **`.env`** next to `finlit_registration_bot.py`:

```
TELEGRAM_BOT_TOKEN=123456789:AA...             # from @BotFather
ORGANIZER_IDS=111111111,222222222              # comma-separated Telegram user_id(s)
LOCAL_TZ=Asia/Tashkent                         # optional
EXCEL_PATH=data/registrations.xlsx             # optional
```

How to get your **user\_id**: run `/whoami` in the bot, or message @userinfobot.

> Keep the token private. Never commit `.env`.

---

## ▶️ Run Locally

```bash
pip install -r requirements.txt
# or: pip install python-telegram-bot==21.4 pandas openpyxl python-dotenv
python finlit_registration_bot.py
```

---

## 🤖 BotFather Checklist

* `/newbot` → name + username (must end with `bot`)
* Copy the **HTTP API token** to `.env` as `TELEGRAM_BOT_TOKEN`
* (Optional) Set commands:

```
start - Ro‘yxatdan o‘tishni boshlash
whoami - User ID ni ko‘rsatish
stats - Registratsiyalar statistikasi (admin)
export_excel - Excel faylini yuborish (admin)
help - Yordam
```

---

## 🧭 User Flow (short)

1. `/start`
2. Ask: Name → Workplace → Career field → Finance/Econ interests
3. Multi‑select: Networking goals
4. Region
5. Multi‑select: Languages (with “Other” text option)
6. Topics of interest
7. Single‑select: Preferred format (Offline/Online/Hybrid)
8. One‑line self‑description
9. Confirmation → Save → Excel update → Organizer DM

---

## 🗂️ Data Model

Table: `registrations`

```
id (PK), telegram_id, telegram_username,
full_name, workplace, career_field,
interests, networking_goals,
region, languages, topics,
meet_format, self_desc,
created_at (local ISO string)
```

---

## 🔒 Privacy & Security

* Tokens are stored only in local `.env`. Do **not** commit `.env`.
* If a token leaks, revoke it in @BotFather and replace.
* SQLite/Excel files may contain personal data. Store and share securely.
* To delete records, remove rows in SQLite/Excel as per your retention policy.

---

## 🛠 Admin Commands

* `/whoami` — returns your Telegram user\_id
* `/stats` — total, today, and this week counts (admins only)
* `/export_excel` — sends the current Excel file (admins only)
* `/help` — command list

> Admins are users listed in `ORGANIZER_IDS`.

---

## 🧩 Customization

You can edit prompt texts and options inside `finlit_registration_bot.py`:

* `NETWORKING_OPTIONS = [ ... ]`
* `LANGUAGE_OPTIONS = [ ... ]`
* `FORMAT_OPTIONS = [ ... ]`
* All question prompts are in handlers like `ask_*` functions.

### Add a group/channel broadcast

Add a command returning chat id (`/whereami`) and post submissions to that id.

---

## 🐳 Docker (optional)

**Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "finlit_registration_bot.py"]
```

**Run**

```bash
docker build -t finlit-bot .
docker run --env-file .env -v $(pwd)/data:/app/data finlit-bot
```

---

## ☁️ Deploy (Railway/Render/VM)

* Create a new service from this repo
* Add environment variables from `.env`
* Set start command: `python finlit_registration_bot.py`
* Ensure **persistent storage** (bind‑mount `data/` or a volume) if you need to keep DB/Excel

---

## 🔍 Troubleshooting

**Bot doesn’t DM organizers**

* Each organizer must **start the bot at least once** (Telegram won’t allow unsolicited DM)
* Check `ORGANIZER_IDS`

**Excel not updating**

* App has no write permission to `data/`
* `openpyxl` not installed → `pip install openpyxl`

**“Forbidden: bot was blocked by the user”**

* The user/organizer blocked the bot or never started it. Ask them to message the bot first.

**No updates arrive**

* Token invalid or wrong bot → re‑check @BotFather token

---

## 📝 License

MIT — see `LICENSE` (add one if needed).

---

## 🙌 Credits

Designed for Finlit Networking (Uzbekistan). Built with python-telegram-bot, pandas, openpyxl.
