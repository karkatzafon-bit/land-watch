#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common.py — לב המערכת. משותף לשני הסקריפטים.
טוען את profile.json, מחלץ מחיר/גודל/סוג קרקע, מסנן,
כותב ל-findings.json ושולח לטלגרם/וואטסאפ.
"""

import json, os, re, sys, time, hashlib
from pathlib import Path
import requests

ROOT = Path(__file__).parent
PROFILE = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
FINDINGS_FILE = ROOT / "findings.json"
FINDINGS_CAP = 800

AREAS            = PROFILE.get("areas", [])
KEYWORDS         = PROFILE.get("keywords", [])
URGENT_BELOW     = PROFILE.get("urgent_below", 0)
MIN_PRICE        = PROFILE.get("min_price", 0)
MAX_PRICE        = PROFILE.get("max_price", 0)
KEEP_IF_NO_PRICE = PROFILE.get("keep_if_no_price", True)
SIZE_MIN         = PROFILE.get("size_min_dunam", 0) or 0
SIZE_MAX         = PROFILE.get("size_max_dunam", 0) or 0
LAND_TYPE        = PROFILE.get("land_type", "all")
SOURCES          = PROFILE.get("sources", {})
MAX_PER_RUN      = PROFILE.get("max_messages_per_run", 25)
FEEDS            = [f for f in PROFILE.get("feeds", []) if f and not f.startswith("PASTE")]

SEND_VIA  = os.environ.get("SEND_VIA", "telegram").lower()
TG_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT   = os.environ.get("TELEGRAM_CHAT_ID", "")
WA_PHONE  = os.environ.get("WHATSAPP_PHONE", "")
WA_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "")

AGRI_TERMS = ["חקלאי", "חקלאית", "להפשרה", "הפשרה", "שינוי ייעוד", "מושע"]


PRICE_RE = re.compile(r'(\d[\d,\.]{1,})\s*(מיליון|מליון|מ׳|אלף|א׳|₪|ש"?ח|שקל)')

def extract_price(text):
    cands = []
    for m in PRICE_RE.finditer(text or ""):
        try:
            num = float(m.group(1).replace(",", "").rstrip("."))
        except ValueError:
            continue
        unit = m.group(2)
        if unit.startswith("מ") and "יליון" in unit or unit in ("מ׳", "מיליון", "מליון"):
            num *= 1_000_000