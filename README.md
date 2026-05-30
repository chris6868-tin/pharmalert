# Telegram DAV Bot — Daily Violation Notification System

## Overview

A production-ready Telegram bot that scrapes the DAV (Drug Administration of Vietnam) website daily for new violation announcements, summarizes PDF documents using Google's Gemini AI, and pushes notifications to subscribed users.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Telegram Bot                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  /start      │  │  /subscribe  │  │  /unsubscribe     │  │
│  │  /help       │  │  /status     │  │  /latest          │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
└──────────┬────────────────────────────────────┬─────────────┘
           │                                    │
┌──────────▼─────────────────────┐  ┌──────────▼──────────────┐
│      Scheduler (APScheduler)   │  │   Database (SQLite)     │
│  ┌──────────────────────────┐  │  │  ┌────────────────────┐  │
│  │  Interval: 60 min check  │  │  │  │  Subscriptions     │  │
│  │  Cron: 08:00 daily push │  │  │  │  Notifications     │  │
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
                    │  - PDF text extracted                 │
                    │  - Prompt: Vietnamese summary         │
                    │  - Markdown-formatted result          │
                    └───────────────────────────────────────┘
```

## Features

- **8 news sources covered**: DAV Vietnam, FDA (Recalls + Shortages + Approvals), EMA (News + Shortages), PRAC Safety Signals — all in one bot
- **Smart PDF summarization**: Extracts text from PDFs using PyMuPDF, sends to Gemini 2.0 Flash for concise Vietnamese summaries
- **Deduplication**: Tracks all processed items; skips re-scraping unchanged content
- **User subscription**: SQLite-backed, per-chat subscriptions with group support
- **Robust scraping**: Async HTTP with retry + timeout; graceful failures don't block notifications
- **Background scheduler**: Non-blocking interval checks + notification push at configurable times (default: 12:00, 17:00)
- **Production-ready**: Structured logging, graceful shutdown signals, containerized with Docker
- **Configurable**: All settings via environment variables (no code changes needed)

## News Sources Covered

| Emoji | Source | Type | Refresh |
|-------|--------|------|---------|
| 🇻🇳 | DAV Vietnam | Xử phạt vi phạm hành chính | 12 tiếng |
| 🇺🇸 | FDA Drug Recall | Class I Recalls (openFDA API) | 12 tiếng |
| ⚠️ | FDA Drug Shortage | Current shortages (openFDA API) | 12 tiếng |
| ✅ | FDA New Approval | Newly approved drugs (Drugs@FDA) | 12 tiếng |
| 🇪🇺 | EMA News | Tin tức + thuốc mới (RSS) | 12 tiếng |
| 🚫 | EMA Medicine Shortage | Thiếu thuốc tại EU (HTML) | 12 tiếng |
| ⚕️ | EMA PRAC Signals | Safety signal recommendations (HTML) | 12 tiếng |

## Prerequisites

- Python 3.12+
- Telegram Bot Token (via [@BotFather](https://t.me/BotFather))
- Gemini API Key (from [Google AI Studio](https://aistudio.google.com/app/apikey))

## Quick Start

### 1. Clone & configure

```bash
git clone <your-repo>
cd telegram-dav-bot
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN and GEMINI_API_KEY
```

### 2. Run with Python

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or: .\.venv\Scripts\Activate.ps1  # Windows

# Install dependencies
pip install -r requirements.txt

# Run
python -m src.main
```

### 3. Run with Docker

```bash
docker compose up -d
docker compose logs -f
```

## Bot Commands

| Command         | Description                                      |
|-----------------|--------------------------------------------------|
| `/start`        | Welcome message + subscription status             |
| `/help`         | Show all commands and help information            |
| `/ping`         | Check that the bot is running                     |
| `/testnotify`   | Run a test scrape and send notifications          |
| `/subscribe`    | Subscribe to daily violation notifications        |
| `/unsubscribe`  | Unsubscribe from notifications                    |
| `/status`       | Show current subscription status                  |
| `/latest [n]`   | Get latest N summaries (default: 5, max: 20)     |

## Health Checks & Manual Verification

- `/ping` — verifies the bot is online and responsive.
- `/testnotify` — performs a manual scrape, builds notifications, and sends a test notification to active subscribers.

## Windows Background / Service Helper

On Windows, you can run the bot in the background using Task Scheduler or a detached PowerShell session.

Example using PowerShell:

```powershell
cd C:\Users\saleb\OneDrive\Desktop\DE\Pharmanews\telegram-dav-bot
.\.venv\Scripts\Activate.ps1
Start-Process -NoNewWindow -FilePath .\.venv\Scripts\python.exe -ArgumentList '-m src.main'
```

If you want a reusable helper, schedule `python -m src.main` as a Task Scheduler task configured to run whether the user is logged on or not.

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env`:

| Variable                    | Default                  | Description                        |
|-----------------------------|--------------------------|------------------------------------|
| `TELEGRAM_BOT_TOKEN`        | *(required)*             | Telegram bot token                 |
| `GEMINI_API_KEY`            | *(required)*             | Gemini API key                     |
| `DAV_LISTINGS_URL`          | *(default provided)*     | DAV listing page URL               |
| `DATABASE_URL`              | `sqlite+aiosqlite:///...`| Database connection string         |
| `LOG_LEVEL`                 | `INFO`                   | Logging level (DEBUG/INFO/WARNING) |
| `CHECK_INTERVAL_MINUTES`    | `720`                    | Interval between scraper runs (12h) |
| `NOTIFICATION_TIMES`        | `12:00,17:00`           | Notification push times (HH:MM)     |
| `TIMEZONE`                  | `Asia/Ho_Chi_Minh`       | Timezone for scheduling             |
| `MAX_PDF_SIZE_MB`           | `10`                     | Max PDF size to process (MB)        |
| `GEMINI_MODEL`              | `gemini-2.0-flash-lite`  | Gemini model ID                    |

## How It Works

1. **Startup**: Bot connects to Telegram and starts the scheduler
2. **Interval check** (every 12h): Scrapes all 7 news sources in parallel
3. **DAV entries**: Downloads PDF → extracts text → Gemini AI → saves to DB
4. **International (FDA/EMA/PRAC)**: Fetches via openFDA API or HTML/RSS → saves to DB
5. **Notification push** (12:00 & 17:00): Sends latest items per source to all subscribers
6. **User commands**: Handle subscribe/unsubscribe/status via Telegram

**No news?** Bot sends a heartbeat message so subscribers know it's still alive.

## FAQ

**Q: Does the bot need to download PDFs?**
A: Yes, Gemini cannot directly fetch external URLs. The bot downloads PDFs to a temp directory, extracts text with PyMuPDF, sends to Gemini, then deletes the temp file immediately.

**Q: What happens if a PDF can't be downloaded?**
A: The notification is skipped gracefully. The error is logged, but the scraper continues with other entries.

**Q: Can I run it without Docker?**
A: Yes, see Quick Start → Run with Python above.

**Q: Can the bot work in group chats?**
A: Yes. Add the bot to a group and use `/subscribe` in the group to receive notifications there.

## Project Structure

```
telegram-dav-bot/
├── src/
│   ├── main.py              # Application entry point
│   ├── bot/
│   │   ├── bot.py           # Bot initialization
│   │   ├── handlers/
│   │   │   ├── __init__.py
│   │   │   ├── subscription.py  # /subscribe, /unsubscribe, /status
│   │   │   ├── commands.py     # /start, /help
│   │   │   └── notifications.py # /latest
│   │   └── router.py        # Command router
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── fetcher.py       # Async HTTP fetcher (HTML + PDF)
│   │   ├── parser.py        # HTML listing parser
│   │   └── pipeline.py      # Full scraping pipeline
│   ├── summarizer/
│   │   ├── __init__.py
│   │   └── gemini.py        # Gemini PDF summarizer
│   ├── scheduler/
│   │   └── jobs.py          # APScheduler jobs (DAV + international)
│   ├── news/
│   │   ├── __init__.py
│   │   ├── base.py          # NewsSourceBase + NewsItem + NewsSource enum
│   │   ├── fda.py          # FDA Enforcement, Shortages, Approvals (openFDA API)
│   │   └── ema.py          # EMA News (RSS), Shortages, PRAC Signals (HTML)
│   └── core/
│       ├── __init__.py
│       ├── config.py        # Settings management
│       ├── logging.py       # Structured logging setup
│       ├── models.py        # Pydantic models
│       ├── exceptions.py    # Custom exceptions
│       └── database.py      # SQLAlchemy async session factory
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Pytest fixtures
│   ├── test_config.py
│   ├── test_parser.py
│   ├── test_summarizer.py
│   └── test_bot.py
├── data/                    # SQLite DB + logs (gitignored)
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## License

MIT
