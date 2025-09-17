#!/usr/bin/env python3
"""
Scrape tenders from one or more websites and store new entries in Google Sheets.
Uses Google Sheets notification rules for free email alerts.
Runs easily in a public GitHub repo (no secrets leaked).
"""

import time
import logging
import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials
from dateutil import parser as date_parser

# ----------------------
# CONFIG (edit these)
# ----------------------
SERVICE_ACCOUNT_FILE = "gcloud-service-account.json"  # created at runtime by GitHub Actions
SPREADSHEET_ID = "YOUR_SPREADSHEET_ID_HERE"          # from Google Sheets URL
TENDERS_SHEET = "Tenders"
PROCESSED_SHEET = "Processed"

TARGETS = [
    {
        "name": "GIZ Live Tenders",
        "url": "https://www.giz.de/en/live-tenders-giz-india#live-tenders",
        "parser": "parse_giz"
    },
    # add more websites here
]

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN = 2.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tender_to_sheets")

# ----------------------
# Utilities
# ----------------------

def safe_get(url):
    r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={
        "User-Agent": "TenderBot/1.0 (+your-email@example.com)"
    })
    r.raise_for_status()
    return r.text

def normalize_date(datestr):
    try:
        return date_parser.parse(datestr, fuzzy=True).date().isoformat()
    except Exception:
        return datestr.strip() if datestr else ""

# ----------------------
# Parser for GIZ tenders
# ----------------------

def parse_giz(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    tender_list = soup.find('h2', string='Live Tenders')
    if tender_list:
        tender_list = tender_list.find_next_sibling('ul')

    items = []
    if tender_list:
        for li in tender_list.find_all('li'):
            a = li.find('a')
            if not a:
                continue
            title = a.get_text(strip=True)
            url = a.get('href')
            tid = url or title
            items.append({
                "tender_id": tid,
                "title": title,
                "publish_date": "",   # unknown
                "closing_date": "",   # unknown
                "url": url,
                "summary": "",
                "source": base_url
            })
    return items

PARSERS = {
    "parse_giz": parse_giz,
}

# ----------------------
# Main logic
# ----------------------

def run():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)

    # Ensure worksheets exist
    try:
        tenders_ws = sh.worksheet(TENDERS_SHEET)
    except gspread.WorksheetNotFound:
        tenders_ws = sh.add_worksheet(title=TENDERS_SHEET, rows="1000", cols="20")
    try:
        processed_ws = sh.worksheet(PROCESSED_SHEET)
    except gspread.WorksheetNotFound:
        processed_ws = sh.add_worksheet(title=PROCESSED_SHEET, rows="1000", cols="2")
        processed_ws.update("A1", [["tender_id"]])

    processed_ids = set(processed_ws.col_values(1)[1:])

    headers = ["tender_id", "title", "publish_date", "closing_date", "url", "summary", "source", "scrape_time"]
    if not tenders_ws.row_values(1):
        tenders_ws.insert_row(headers, 1)

    new_rows = []
    new_ids = []

    for target in TARGETS:
        name = target["name"]
        url = target["url"]
        parser_fn = PARSERS[target["parser"]]
        logger.info("Scraping %s ...", name)
        try:
            html = safe_get(url)
            items = parser_fn(html, base_url=url)
            for it in items:
                tid = it["tender_id"]
                if tid in processed_ids:
                    continue
                scrape_time = time.strftime("%Y-%m-%d %H:%M:%S")
                row = [
                    tid,
                    it["title"],
                    it.get("publish_date", ""),
                    it.get("closing_date", ""),
                    it["url"],
                    it.get("summary", ""),
                    it.get("source", ""),
                    scrape_time
                ]
                new_rows.append(row)
                new_ids.append([tid])
                processed_ids.add(tid)
            time.sleep(SLEEP_BETWEEN)
        except Exception as e:
            logger.error("Error scraping %s: %s", name, e)

    if new_rows:
        tenders_ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        processed_ws.append_rows(new_ids, value_input_option="USER_ENTERED")
        logger.info("Added %d new tenders.", len(new_rows))
    else:
        logger.info("No new tenders found.")

if __name__ == "__main__":
    run()
