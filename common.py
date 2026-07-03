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
        elif unit.startswith("א"):
            num *= 1_000
        if 10_000 <= num <= 50_000_000:
            cands.append(num)
    return min(cands) if cands else None

SIZE_RE = re.compile(r'(\d[\d,\.]*)\s*(דונם|מ"ר|מ״ר|מטר רבוע)')

def extract_size_dunam(text):
    for m in SIZE_RE.finditer(text or ""):
        try:
            num = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2) != "דונם":
            num = num / 1000.0
        if 0.05 <= num <= 5000:
            return round(num, 2)
    return None

def detect_land_type(text):
    t = text or ""
    if any(w in t for w in AGRI_TERMS):
        return "agri"
    if any(w in t for w in ("מאושר לבנייה", "היתר בנייה", "תב\"ע מאושרת", "מגרש למגורים")):
        return "build"
    return "unknown"


def evaluate(text, price=None, size=None, ltype=None):
    t = text or ""
    if KEYWORDS and not any(k in t for k in KEYWORDS):
        return False, "ללא מילת מפתח"
    if AREAS and not any(a in t for a in AREAS):
        return False, "מחוץ לאזורים"
    if price is not None:
        if MIN_PRICE and price < MIN_PRICE:
            return False, "מתחת למינימום"
        if MAX_PRICE and price > MAX_PRICE:
            return False, "מעל תקרה"
    elif not KEEP_IF_NO_PRICE:
        return False, "ללא מחיר"
    if size is not None and (SIZE_MIN or SIZE_MAX):
        if SIZE_MIN and size < SIZE_MIN:
            return False, "קטן מדי"
        if SIZE_MAX and size > SIZE_MAX:
            return False, "גדול מדי"
    if LAND_TYPE == "build_only" and ltype == "agri":
        return False, "חקלאי/להפשרה"
    return True, ""

def is_urgent(price):
    return price is not None and URGENT_BELOW and price < URGENT_BELOW


def load_findings():
    if FINDINGS_FILE.exists():
        try:
            return json.loads(FINDINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_findings(items):
    items = items[:FINDINGS_CAP]
    FINDINGS_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

def make_finding(source, title, link, price=None, size=None, ltype="unknown",
                 passed=True, reason="", kind="listing"):
    return {
        "id": hashlib.sha1(f"{link}|{title}".encode("utf-8")).hexdigest()[:16],
        "ts": int(time.time()),
        "source": source,
        "kind": kind,
        "title": (title or "")[:180],
        "link": link or "",
        "price": price,
        "size_dunam": size,
        "land_type": ltype,
        "urgent": bool(is_urgent(price)),
        "passed": bool(passed),
        "reason": reason,
    }

def add_findings(new_items):
    if not new_items:
        return
    cur = load_findings()
    known = {it.get("id") for it in cur}
    fresh = [it for it in new_items if it["id"] not in known]
    save_findings(fresh + cur)


def send_telegram(msg):
    if not (TG_TOKEN and TG_CHAT):
        raise RuntimeError("חסר TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID")
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT, "text": msg,
                            "disable_web_page_preview": False}, timeout=20)
    r.raise_for_status()

def send_whatsapp(msg):
    if not (WA_PHONE and WA_APIKEY):
        raise RuntimeError("חסר WHATSAPP_PHONE או CALLMEBOT_APIKEY")
    r = requests.get("https://api.callmebot.com/whatsapp.php",
                     params={"phone": WA_PHONE, "text": msg, "apikey": WA_APIKEY},
                     timeout=20)
    r.raise_for_status()

def notify(msg):
    if SEND_VIA == "whatsapp":
        send_whatsapp(msg)
    else:
        send_telegram(msg)

SOURCE_LABEL = {"yad2": "יד2", "madlan": "מדלן", "rmi": "רמ\"י",
                "facebook": "פייסבוק", "web": "רשת"}

def format_listing_msg(f):
    head = f"🔴 דחוף — מתחת ל-{URGENT_BELOW:,} ₪!\n" if f["urgent"] else ""
    ptxt = f"💰 ~{int(f['price']):,} ₪" if f["price"] else "💰 מחיר לא זוהה — לבדוק"
    extra = ""
    if f.get("size_dunam"):
        extra += f" · 📐 {f['size_dunam']} דונם"
    if f.get("land_type") == "agri":
        extra += " · ⚠️ חקלאי/להפשרה"
    src = SOURCE_LABEL.get(f["source"], f["source"])
    return f"{head}🏡 מודעה חדשה ({src})\n{f['title']}\n{ptxt}{extra}\n🔗 {f['link']}"

def format_fb_msg(f):
    tail = f"\n🔗 {f['link']}" if f["link"] else "\n(היכנס לפייסבוק לראות את הפוסט)"
    return f"📘 פוסט חדש בפייסבוק\n{f['title']}{tail}"

def send_findings(findings):
    to_send = [f for f in findings if f["passed"]]
    to_send.sort(key=lambda f: (not f["urgent"], f["price"] is None,
                                f["price"] if f["price"] is not None else 0))
    sent = 0
    for f in to_send[:MAX_PER_RUN]:
        msg = format_fb_msg(f) if f["kind"] == "fb_post" else format_listing_msg(f)
        try:
            notify(msg); sent += 1; time.sleep(1)
        except Exception as e:
            print(f"[warn] send failed: {e}", file=sys.stderr)
    return sent


def load_seen(path):
    p = ROOT / path
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return list(d), set(d)
        except Exception:
            return [], set()
    return [], set()

def save_seen(path, lst, cap=8000):
    (ROOT / path).write_text(json.dumps(lst[-cap:], ensure_ascii=False),
                             encoding="utf-8")