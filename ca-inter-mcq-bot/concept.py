#!/usr/bin/env python3
"""CA Inter – Concept of the Day (9:00 AM IST, Mon–Sat, Group 1 + Group 2 topics).

concepts.json      : {"YYYY-MM-DD": {"g1": "<html>", "g2": "<html>"}}
concept_state.json : {"posted": ["YYYY-MM-DD:g1", ...]}  – guard so a re-run never posts twice

Usage: python concept.py [post|preview]   (env WAIT=1 waits until 9:00 AM IST; DATE=YYYY-MM-DD overrides today)
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
IST = timezone(timedelta(hours=5, minutes=30))
CONTENT, STATE, CONFIG = (os.path.join(HERE, f) for f in ("concepts.json", "concept_state.json", "config.json"))


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def api(method, **params):
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        sys.exit("BOT_TOKEN is not set.")
    body = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
    base = os.environ.get("TG_API", "https://api.telegram.org")
    req = urllib.request.Request(f"{base}/bot{token}/{method}", data=body,
                                 headers={"Content-Type": "application/json"})
    res = {}
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r)
        except urllib.error.HTTPError as err:
            res = json.load(err)
        except (urllib.error.URLError, TimeoutError) as err:
            res = {"ok": False, "description": str(err), "parameters": {"retry_after": 5}}
        wait = (res.get("parameters") or {}).get("retry_after")
        if res.get("ok") or not wait or attempt == 5:
            break
        print(f"Telegram {method}: retry in {wait}s")
        time.sleep(min(int(wait) + 1, 60))
    if not res.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {res.get('description')}")
    return res["result"]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "post"
    now = datetime.now(IST)
    date = os.environ.get("DATE") or now.strftime("%Y-%m-%d")
    content = load(CONTENT, {})
    day = content.get(date)
    if not day:
        print(f"{date}: no Concept of the Day content. Nothing to post.")
        return
    if mode == "preview":
        for g in ("g1", "g2"):
            print(f"--- {g} ---\n{day[g]}\n")
        return
    if datetime.strptime(date, "%Y-%m-%d").weekday() == 6 and not os.environ.get("DATE"):
        print("Sunday: no Concept of the Day.")
        return
    if os.environ.get("WAIT") == "1":
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        wait = (target - datetime.now(IST)).total_seconds()
        if wait > 0:
            print(f"Waiting {int(wait)} s until 9:00 AM IST")
            time.sleep(wait)
    cfg = load(CONFIG)
    chat = cfg["chat_id"]
    topics = cfg["group_topics"][str(chat)]
    state = load(STATE, {"posted": []})
    for g, grp in (("g1", "Group 1"), ("g2", "Group 2")):
        key = f"{date}:{g}"
        if key in state["posted"]:
            print(f"{key} already posted.")
            continue
        api("sendMessage", chat_id=chat, message_thread_id=topics[grp], text=day[g],
            parse_mode="HTML", disable_web_page_preview=True)
        state["posted"].append(key)
        state["posted"] = state["posted"][-400:]
        save(STATE, state)
        print(f"Posted {key} to {grp}.")


if __name__ == "__main__":
    main()
