#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
email_ingest.py — קורא את תיבת המכונה (IMAP), מזהה מקור לפי השולח:
יד2/מדלן/רמ"י = מודעות · facebookmail = פוסטים · השאר = רשת.
כותב ל-findings.json ושולח לטלגרם לפי profile.json.
"""

import sys, hashlib, imaplib, email
from email.header import decode_header
import urllib.parse
from bs4 import BeautifulSoup

import common as C

SEEN_PATH = "seen_email.json"

EMAIL_USER   = C.os.environ.get("EMAIL_USER", "")
EMAIL_PASS   = C.os.environ.get("EMAIL_APP_PASSWORD", "")
EMAIL_HOST   = C.os.environ.get("EMAIL_HOST", "imap.gmail.com")
EMAIL_FOLDER = C.os.environ.get("EMAIL_FOLDER", "INBOX")

LISTING_DOMAINS = ("yad2.co.il", "madlan.co.il", "land.gov.il", "gov.il",
                   "komo.co.il", "onmap.co.il")


def decode_hdr(raw):
    if not raw:
        return ""
    out = ""
    for txt, enc in decode_header(raw):
        if isinstance(txt, bytes):
            try:
                out += txt.decode(enc or "utf-8", errors="replace")
            except Exception:
                out += txt.decode("utf-8", errors="replace")
        else:
            out += txt
    return out

def clean_link(link):
    try:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        if "url" in params:
            return params["url"][0]
        if "q" in params and params["q"][0].startswith("http"):
            return params["q"][0]
    except Exception:
        pass
    return link

def get_html_body(msg):
    if msg.is_multipart():
        html_part = text_part = None
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html" and html_part is None:
                html_part = part
            elif ct == "text/plain" and text_part is None:
                text_part = part
        part = html_part or text_part
        if not part:
            return ""
    else:
        part = msg
    try:
        payload = part.get_payload(decode=True)
        return payload.decode(part.get_content_charset() or "utf-8",
                              errors="replace")
    except Exception:
        return ""

def source_of(url):
    if "yad2" in url: return "yad2"
    if "madlan" in url: return "madlan"
    if "land.gov.il" in url or "gov.il" in url: return "rmi"
    return "web"

def extract_listings(body_html):
    soup = BeautifulSoup(body_html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        url = clean_link(a["href"])
        if not url.startswith("http"):
            continue
        if not any(d in url for d in LISTING_DOMAINS):
            continue
        title = a.get_text(" ", strip=True)
        ctx = title
        for up in (a.parent, getattr(a.parent, "parent", None)):
            if up is not None:
                ctx += " " + up.get_text(" ", strip=True)
        if not title:
            title = "מודעה (ללא כותרת) — היכנס לבדוק"
        out.append((title[:160], url, ctx))
    return out

def fb_link(body_html):
    soup = BeautifulSoup(body_html, "html.parser")
    for a in soup.find_all("a", href=True):
        if "facebook.com" in a["href"]:
            return a["href"]
    return ""


def main():
    if not (EMAIL_USER and EMAIL_PASS):
        print("[error] חסרים EMAIL_USER / EMAIL_APP_PASSWORD", file=sys.stderr)
        sys.exit(1)

    seen_list, seen_set = C.load_seen(SEEN_PATH)
    first_run = len(seen_set) == 0

    M = imaplib.IMAP4_SSL(EMAIL_HOST)
    M.login(EMAIL_USER, EMAIL_PASS)
    M.select(EMAIL_FOLDER)
    typ, data = M.search(None, "UNSEEN")
    ids = data[0].split() if data and data[0] else []

    findings = []
    for num in ids:
        typ, msg_data = M.fetch(num, "(BODY.PEEK[])")
        if typ != "OK" or not msg_data or not msg_data[0]:
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        from_addr = decode_hdr(msg.get("From", "")).lower()
        body = get_html_body(msg)
        M.store(num, "+FLAGS", "\\Seen")

        if "facebookmail.com" in from_addr:
            if not C.SOURCES.get("facebook", True):
                continue
            subject = decode_hdr(msg.get("Subject", "")) or "פוסט חדש בקבוצה"
            msgid = msg.get("Message-ID", "") or (subject + from_addr)
            uid = "fb:" + hashlib.sha1(msgid.encode("utf-8")).hexdigest()[:16]
            if uid in seen_set:
                continue
            seen_set.add(uid); seen_list.append(uid)
            blob = subject + " " + BeautifulSoup(body, "html.parser") \
                                       .get_text(" ", strip=True)
            relevant = (any(k in blob for k in C.KEYWORDS)
                        or any(a in blob for a in C.AREAS))
            findings.append(C.make_finding(
                "facebook", subject[:160], fb_link(body),
                passed=relevant, reason="" if relevant else "לא רלוונטי לאזור",
                kind="fb_post"))
            continue

        for title, url, ctx in extract_listings(body):
            uid = hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:16]
            if uid in seen_set:
                continue
            seen_set.add(uid); seen_list.append(uid)
            src = source_of(url)
            if not C.SOURCES.get("yad2", True) and src in ("yad2", "madlan"):
                continue
            price = C.extract_price(ctx)
            size  = C.extract_size_dunam(ctx)
            ltype = C.detect_land_type(ctx)
            passed, reason = C.evaluate(ctx, price, size, ltype)
            findings.append(C.make_finding(src, title, url, price, size,
                                           ltype, passed, reason))

    M.logout()

    if first_run:
        C.save_seen(SEEN_PATH, seen_list)
        try:
            C.notify("✅ איחוד המיילים הופעל (יד2 / פייסבוק / Alerts). מעכשיו — רק חדש.")
        except Exception as e:
            print(f"[warn] init notify: {e}", file=sys.stderr)
        print(f"email first run: seeded {len(seen_set)}.")
        return

    C.add_findings(findings)
    sent = C.send_findings(findings)
    C.save_seen(SEEN_PATH, seen_list)
    print(f"email done. new={len(findings)} sent={sent} seen={len(seen_set)}")


if __name__ == "__main__":
    main()