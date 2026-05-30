@echo off
:: Change directory to where this batch file is located
cd /d "%~dp0"

echo [%date% %time%] Starting local DAV scraper... >> scraper_log.log

:: Execute scraper with the virtual environment Python interpreter
.venv\Scripts\python.exe scrape_dav_local.py >> scraper_log.log 2>&1

echo [%date% %time%] Scraper execution completed. >> scraper_log.log
