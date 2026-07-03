#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
land_watch.py — סורק את פידי ה-RSS (Google Alerts) שמוגדרים ב-profile.json,
כותב כל ממצא ל-findings.json ושולח לטלגרם את מה שעבר סינון.
רץ כל שעה ב-GitHub Actions.
"""

import sys, hashlib, html, re
import urllib.parse
import feedparser

import common as C

SEEN_PATH = "seen.json"


def item_id(entry):
    raw = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

def clean_link(link):
    try:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        if "url" in params:
            return params["url"][0]
    except Exception:
        pass
    return link

def strip_html(s):
    return html.unescape(re.sub("<[^>]+>", " ", s or "")).strip()


def main():
    if not C.SOURCES.get("alerts", True):
        print("alerts source disabled in profile — skipping.")
        return
    if not C.FEEDS:
        print("no feeds configured in profile.json — nothing to do.")
        return

    seen_list, seen_set = C.load_seen(SEEN_PATH)
    first_run = len(seen_set) == 0

    entries = []
    for url in C.FEEDS:
        try:
            entries.extend(feedparser.parse(url).entries)
        except Exception as e:
            print(f"[warn] feed failed: {url} :: {e}", file=sys.stderr)

    if first_run:
        for e in entries:
            iid = item_id(e)
            if iid not in seen_set:
                seen_set.add(iid); seen_list.append(iid)
        C.save_seen(SEEN_PATH, seen_list)
        try:
            C.notify("✅ ניטור הרשת הופעל. מעכשיו — רק ממצאים חדשים.")
        except Exception as e:
            print(f"[warn] init notify: {e}", file=sys.stderr)
        print(f"first run: seeded {len(seen_set)}.")
        return

    findings = []
    for e in entries:
        iid = item_id(e)
        if iid in seen_set:
            continue
        seen_set.add(iid); seen_list.append(iid)

        title = strip_html(e.get("title", ""))
        blob = f"{title} {strip_html(e.get('summary', ''))}"
        link = clean_link(e.get("link", ""))

        price = C.extract_price(blob)
        size  = C.extract_size_dunam(blob)
        ltype = C.detect_land_type(blob)
        passed, reason = C.evaluate(blob, price, size, ltype)

        src = "rmi" if ("land.gov.il" in link or "gov.il" in link) else "web"
        findings.append(C.make_finding(src, title, link, price, size, ltype,
                                       passed, reason))

    C.add_findings(findings)
    sent = C.send_findings(findings)
    C.save_seen(SEEN_PATH, seen_list)
    print(f"done. new={len(findings)} sent={sent} seen={len(seen_set)}")


if __name__ == "__main__":
    main()