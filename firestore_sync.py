#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
firestore_sync.py — הגשר בין הצינור הקיים ל-Firebase.
שלושה מצבים (לפי הארגומנט הראשון):
  profile  — לפני הסריקה: מושך את פרופיל הסינון מ-Firestore אל profile.json
             (כך שעריכת הפרופיל באתר משפיעה על הסריקה הבאה).
  findings — אחרי הסריקה: מעלה ממצאים חדשים מ-findings.json אל אוסף feed,
             ומעדכן את meta/pipeline (בשביל טאב "מצב" באתר).
  heartbeat — פעימת-לב: הודעת טלגרם יומית "הצינור חי" עם סיכום 24 שעות.

דורש Secret בשם FIREBASE_SERVICE_ACCOUNT (תוכן קובץ ה-JSON של חשבון השירות).
"""

import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).parent
FINDINGS_FILE = ROOT / "findings.json"
PROFILE_FILE = ROOT / "profile.json"


def get_db():
    from google.cloud import firestore
    from google.oauth2 import service_account
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
    if not raw:
        print("[sync] FIREBASE_SERVICE_ACCOUNT missing — skipping.", file=sys.stderr)
        return None
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info)
    return firestore.Client(project=info["project_id"], credentials=creds)


def sync_profile(db):
    """Firestore → profile.json (העריכה באתר קובעת את הסינון)."""
    snap = db.collection("profile").document("main").get()
    if not snap.exists:
        print("[sync] no profile in Firestore — keeping local profile.json.")
        return
    data = snap.to_dict() or {}
    data.pop("updatedAt", None)
    data.pop("by", None)
    PROFILE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[sync] profile.json updated from Firestore ({len(data)} keys).")


def sync_findings(db):
    """findings.json → אוסף feed (רק חדשים, לפי id)."""
    if not FINDINGS_FILE.exists():
        print("[sync] no findings.json — nothing to upload.")
        return
    items = json.loads(FINDINGS_FILE.read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("findings", [])
    col = db.collection("feed")
    new = 0
    for it in items[:400]:  # העדכניים ביותר
        fid = str(it.get("id") or it.get("hash") or hash(it.get("link", "")))[:60]
        ref = col.document(fid)
        if not ref.get().exists:
            it["_syncedAt"] = int(time.time() * 1000)
            ref.set(it)
            new += 1
    db.collection("meta").document("pipeline").set({
        "lastRun": int(time.time() * 1000),
        "lastNew": new,
        "totalInFile": len(items),
    }, merge=True)
    print(f"[sync] uploaded {new} new findings to Firestore (of {len(items)} in file).")


def heartbeat(db):
    """פעם ביום: הודעת טלגרם שהצינור חי + ספירת ממצאים מ-24 השעות."""
    import requests
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (tok and chat):
        print("[hb] telegram secrets missing — skipping.")
        return
    day_ago = int((time.time() - 86400) * 1000)
    cnt = 0
    if db is not None:
        try:
            for _ in db.collection("feed").where("_syncedAt", ">=", day_ago).stream():
                cnt += 1
        except Exception as e:
            print(f"[hb] count failed: {e}", file=sys.stderr)
    msg = f"💓 מפקדת קרקעות — הצינור חי.\n24 שעות אחרונות: {cnt} ממצאים חדשים בפיד."
    requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                  data={"chat_id": chat, "text": msg}, timeout=20)
    print("[hb] heartbeat sent.")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "findings"
    db = get_db()
    if mode == "profile":
        if db: sync_profile(db)
    elif mode == "heartbeat":
        heartbeat(db)
    else:
        if db: sync_findings(db)


if __name__ == "__main__":
    main()