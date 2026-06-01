# Telegram Pharmanews / Pharmalert Bot — Daily Violation Notification & AI Insight System

## Overview

A production-ready Telegram bot that scrapes the DAV (Drug Administration of Vietnam) website daily for new violation announcements, summarizes PDF documents using Google's Gemini AI, aggregates international pharmaceutical regulatory updates (FDA & EMA), and sends structured daily push notifications. 

Additionally, it features **PharmaTech Daily** — an automated, AI-generated daily pharmaceutical R&D and market insights system with an interactive **Admin approval workflow** to ensure premium, high-quality content delivery.

---

## Architecture & Workflows

### 1. Daily Notification Pipeline (Scraper)
```
┌──────────────────────────────────────────────────────────────┐
│                        Telegram Bot                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  /start      │  │  /sources    │  │  /status          │  │
│  │  /help       │  │  /subscribe  │  │  /unsubscribe     │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
└──────────┬────────────────────────────────────┬─────────────┘
           │                                    │
┌──────────▼─────────────────────┐  ┌──────────▼──────────────┐
│      Scheduler (APScheduler)   │  │  Database (PostgreSQL)  │
│  ┌──────────────────────────┐  │  │  ┌────────────────────┐  │
│  │  Interval: 30 min check  │  │  │  │  Subscriptions     │  │
│  │  Cron: Push slots        │  │  │  │  Announcements     │  │
│  │  (e.g., 12:00, 18:00)    │  │  │  │  Notifications     │  │
│  └──────────────────────────┘  │  │  └────────────────────┘  │
└──────────┬─────────────────────┘  └──────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────────┐
│                      Scraper Pipeline                         │
│  ┌────────────────────┐    ┌──────────────────────────────┐ │
│  │  DAV Listing Page  │───▶│  Parse new entries (HTML)    │ │
│  └────────────────────┘    └──────────────┬───────────────┘ │
│                                           │                  │
│                   ┌──────────────────────▼───────────────┐  │
│                   │  Filter: Skip already-processed PDFs │  │
│                   └──────────────────────┬───────────────┘  │
│                                           │                  │
│  ┌───────────────────────────────────────▼───────────────┐  │
│  │  PDF Fetcher (async stream, size limit, retry)        │  │
│  └───────────────────────────────────────┬───────────────┘  │
│                                          │                  │
└──────────────────────────────────────────┼──────────────────┘
                                           │
                    ┌──────────────────────▼───────────────┐
                    │  Gemini Summarizer                   │
                    │  - PDF text extracted (PyMuPDF)       │
                    │  - System Prompt: DAV layout format   │
                    │  - Markdown-formatted result          │
                    └───────────────────────────────────────┘
```

### 2. PharmaTech Daily Workflow (Admin Approval)
```
  [⏰ Scheduled Time / 09:00]
              │
              ▼
    _generate_pharma_daily()
              │
              ├──▶ Query DB: Fetch 30 recent topics (to avoid repetition)
              │
              ├──▶ Call Gemini: Write technical article (alternating topic)
              │
              ├──▶ Save to DB: As pending draft (processed_at = None)
              │
              ▼
   [📨 Sent to Admin Chat] ──▶ Displays Preview + Action Buttons
              │
      ┌───────┴───────────────────────┐
      ▼                               ▼
 [✅ Duyệt & Phát sóng]       [♻️ Tạo bài khác]
      │                               │
      ├──▶ Update DB: Approved        ├──▶ Delete Draft from DB
      ├──▶ Broadcast to subscribers   ├──▶ Trigger new Gemini call
      └──▶ Delete Admin Buttons       └──▶ Replace old Telegram draft
```

---

## Features

- **8 News Sources Covered**: DAV Vietnam (Violations & Registrations), FDA (Recalls, Shortages, Approvals), EMA (News, Shortages), and PRAC Safety Signals — all in one bot.
- **Smart PDF Summarization**: Downloads PDF announcements, extracts text using PyMuPDF, and generates concise, structured Vietnamese summaries via Gemini AI.
- **PharmaTech Daily**: Automated daily high-technical R&D and market insights alternating topics by weekday:
  * **Mon, Wed, Fri**: 💡 *Sáng tạo Bào chế & Kỹ thuật tá dược* (Formulation & Excipients)
  * **Tue, Thu**: 📈 *Xu hướng Kinh tế Dược & Patent Cliff* (Economics & Strategy)
  * **Sat, Sun**: 🔬 *Câu chuyện Lâm sàng & Đột phá Sinh học* (Clinical Trials & Biologics)
- **Interactive Admin Approval**: Preview drafts in Telegram with inline buttons to approve/broadcast or regenerate with a single tap.
- **User Subscription Control**: Per-chat subscriptions using PostgreSQL/SQLite. Users can customize which of the 8 sources they want to receive notifications for via `/sources`.
- **Coffee Signature**: Subtle, non-intrusive footer for community coffee donations.
- **Robust Scraper**: Asynchronous fetching, timeout protection, backoff retries, and rate limits to guarantee absolute stability.
- **Structured Loguru Logging**: High-fidelity logs, automatic database migrations, and graceful shutdown support.

---

## News Sources Covered

| Emoji | Source | Type / Content | Interval |
| :---: | :--- | :--- | :---: |
| 🇻🇳 | **DAV Vietnam** | Xử phạt vi phạm hành chính | 30 Phút |
| 🇻🇳 | **DAV Registration** | Đăng ký thuốc / Cấp phép lưu hành | 30 Phút |
| 🇺🇸 | **FDA Drug Recall** | Class I Recalls (openFDA API) | 30 Phút |
| ⚠️ | **FDA Drug Shortage** | Current shortages (openFDA API) | 30 Phút |
| ✅ | **FDA New Approval** | Newly approved drugs (Drugs@FDA) | 30 Phút |
| 🇪🇺 | **EMA News** | Tin tức tổng hợp (RSS) | 30 Phút |
| 🚫 | **EMA Medicine Shortage** | Thiếu thuốc tại thị trường EU (HTML) | 30 Phút |
| ⚕️ | **EMA PRAC Signals** | Safety recommendations (HTML) | 30 Phút |

---

## Prerequisites

- **Python 3.12+**
- **Telegram Bot Token** (obtain from [@BotFather](https://t.me/BotFather))
- **Gemini API Key** (obtain from [Google AI Studio](https://aistudio.google.com/app/apikey))
- **Database**: PostgreSQL (Supabase/Neon) for production, SQLite (aiosqlite) for local development.

---

## Quick Start

### 1. Clone & Configure
```bash
git clone <your-repository-url>
cd telegram-dav-bot
cp .env.example .env
# Edit .env and supply your API keys and credentials
```

### 2. Local Setup & Execution
We recommend using a virtual environment:
```bash
# Create and activate virtual environment
python -m venv .venv
# On Windows:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python -m src.main
```

### 3. Deploy on Render
This application is fully prepared for **Render** deployment.
- **Environment**: Python
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python -m src.main`
- **Port**: Render injects the `PORT` env var automatically. The bot fires up a lightweight `aiohttp` web server to respond to Render's `/health` check.

---

## Configuration Variables

Copy `.env.example` to `.env` to configure the bot. Below are the key environment variables:

| Variable | Type | Default | Description |
| :--- | :---: | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | String | *(Required)* | Telegram Bot token from @BotFather |
| `GEMINI_API_KEY` | String | *(Required)* | Google Gemini AI API key |
| `ADMIN_TELEGRAM_CHAT_ID` | Integer | `0` | Numeric Chat ID of the Bot Admin to receive daily drafts and control commands. |
| `ENABLE_PHARMA_DAILY` | Boolean | `false` | Enable/disable the PharmaTech Daily AI generator. |
| `PHARMA_DAILY_TIME` | String | `07:30` | Time slot for generating daily drafts (`HH:MM` local time). |
| `DATABASE_URL` | String | `sqlite+aiosqlite:///./data/bot.db` | PostgreSQL or SQLite async connection string. |
| `NOTIFICATION_TIMES` | String | `12:00,17:00` | Chron times for subscriber push notifications (comma separated `HH:MM`). |
| `TIMEZONE` | String | `Asia/Ho_Chi_Minh` | Target timezone for daily tasks and scraper cron. |
| `GEMINI_MODEL` | String | `gemini-flash-lite-latest` | Gemini model ID (e.g., `gemini-2.0-flash-lite`). |
| `CHECK_INTERVAL_MINUTES` | Integer | `30` | Minutes between execution checks of web scrapers. |
| `ENABLE_DAV_SCRAPING` | Boolean | `true` | Enable/disable DAV crawlers (useful if server IP is country-blocked). |
| `ENABLE_INTERNATIONAL_SOURCES`| Boolean | `true` | Enable/disable FDA/EMA/PRAC ciders. |

---

## Bot Commands

| Command | Permission | Description |
| :--- | :---: | :--- |
| `/start` | Public | Welcome message, bot description, and registration status. |
| `/help` | Public | Comprehensive list of available commands and usage guide. |
| `/subscribe` | Public | Subscribe chat to receive automated daily summaries. |
| `/unsubscribe`| Public | Unsubscribe chat from receiving push updates. |
| `/status` | Public | Check current subscription state and enabled sources. |
| `/sources` | Public | Open interactive settings menu to customize your news sources. |
| `/latest [n]`| Public | Query the database and return the latest `n` summaries (default: 5). |
| `/ping` | Public | Heartbeat check to verify the bot is online. |
| `/testnotify` | **Admin Only**| Trigger a manual scraper loop and deliver fresh summaries to active users. |

---

## Manual Broadcast Tool

If you want to broadcast a custom text message (like feature announcements, updates, or maintenance notes) to all active subscribers, you can run the helper script:

```bash
# Execute custom broadcast to all active subscribers in Supabase
.venv\Scripts\python.exe broadcast_feature.py
```

*Note: You can easily customize the message content inside `broadcast_feature.py` before running.*

---

## Project Structure

```
telegram-dav-bot/
├── src/
│   ├── main.py              # Application entry point & service coordinator
│   ├── bot/
│   │   ├── bot.py           # Telegram bot application setup
│   │   ├── router.py        # Command and callback query routing
│   │   └── handlers/
│   │       ├── commands.py     # Command handlers (/start, /help, /ping)
│   │       ├── subscription.py # Subscriptions, /sources, interactive configurations
│   │       ├── notifications.py# Fetching and manual queries (/latest)
│   │       └── admin.py        # Admin panel, approval, and regeneration callback logic
│   ├── scraper/
│   │   ├── fetcher.py       # Asynchronous HTTP/PDF download client
│   │   ├── parser.py        # HTML tree scraping and element extraction
│   │   └── pipeline.py      # Unified workflow pipeline (crawling to SQLite/Postgres)
│   ├── summarizer/
│   │   └── gemini.py        # Gemini API client, text extraction & prompt engineering
│   ├── scheduler/
│   │   └── jobs.py          # Cron jobs (Scrapers, push notifications, daily insight generator)
│   ├── news/
│   │   ├── base.py          # NewsSource base types and structures
│   │   ├── fda.py           # FDA API parsers (Recalls, shortage, approval trackers)
│   │   └── ema.py           # EMA HTML & RSS parsers (News, shortages, safety signals)
│   └── core/
│       ├── config.py        # Environment settings and validations (Pydantic Settings)
│       ├── database.py      # Database setup and SQLAlchemy async sessions
│       ├── models.py        # Declarative SQLAlchemy ORM schemas
│       ├── logging.py       # Custom loguru structured configurations
│       └── exceptions.py    # Standard custom application exceptions
├── data/                    # Local database folder (SQLite data storage, gitignored)
├── tests/                   # Pytest automation scripts
├── broadcast_feature.py     # Administrative manual broadcast script
├── pyproject.toml           # Python dependency specification metadata
├── Dockerfile               # Production container config
└── README.md                # System documentation
```

---

## License

This project is licensed under the MIT License - see the LICENSE file for details.
