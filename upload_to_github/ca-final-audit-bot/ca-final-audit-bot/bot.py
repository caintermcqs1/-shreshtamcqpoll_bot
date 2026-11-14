#!/usr/bin/env python3
"""CA Final Audit Daily MCQ bot (SHRESHTA's FRATERNITY! – topic "CA Final Audit MCQs").

plan.json  : list of days. Each day = {"day", "date" (YYYY-MM-DD), "morning": [messages], "evening": "answers text"}
             morning message = {"type": "text", "text": ...}  or
                               {"type": "quiz", "question", "options"[4], "correct" (0-3), "explanation"}
state.json : progress per date, so a re-run continues where it stopped and never posts twice.

Modes:
  post     – post today's questions (10:30 AM IST)
  answers  – close today's polls and post the answers (8:30 PM IST)
  preview  – print today's (or DATE=YYYY-MM-DD) posts without sending
  test     – send a day's posts to TEST_CHAT only (DATE=YYYY-MM-DD optional); saves nothing
"""
import csv, io, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN, STATE, CONFIG = (os.path.join(HERE, f) for f in ("plan.json", "state.json", "config.json"))
IST = timezone(timedelta(hours=5, minutes=30))


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
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=body,
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


def today():
    return os.environ.get("DATE", "").strip() or datetime.now(IST).strftime("%Y-%m-%d")


def target(cfg):
    test = os.environ.get("TEST_CHAT", "").strip()
    if test:
        return {"chat_id": int(test), "message_thread_id": None}
    return {"chat_id": int(cfg["chat_id"]), "message_thread_id": cfg.get("thread_id")}


def fix_text(t):
    """Repair emojis garbled by Google's CSV import (4-byte UTF-8 read as Latin-1, e.g. 'ð\x9f\x9f¦' -> '🟦')."""
    def rep(m):
        try:
            return m.group(0).encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return m.group(0)
    return re.sub(r"[\xf0-\xf4][\x80-\xbf]{3}", rep, t or "")


def sheet_plan(url):
    """Read the plan from a Google Sheet published as CSV (one row per message).
    Columns: date, day, part (morning/evening), seq, type (text/quiz), text, A, B, C, D, correct (A-D), explanation"""
    with urllib.request.urlopen(url, timeout=60) as r:
        rows = list(csv.DictReader(io.StringIO(r.read().decode("utf-8-sig"))))
    rows = [{k: fix_text(v) for k, v in row.items()} for row in rows]
    days = {}
    for row in rows:
        date = (row.get("date") or "").strip()
        if not date:
            continue
        if not (len(date) == 10 and date[4] == "-" and date[7] == "-"):
            # the sheet may show dates in another format: rebuild from the day number (Day 1 = 13 Nov 2026)
            date = (datetime(2026, 11, 13) + timedelta(days=int(float(row["day"])) - 1)).strftime("%Y-%m-%d")
        d = days.setdefault(date, {"day": int(float(row.get("day") or 0)), "date": date, "morning": [], "evening": "", "_m": []})
        if (row.get("part") or "").strip().lower() == "evening":
            d["evening"] = row["text"]
            continue
        seq = float(row.get("seq") or 0)
        if (row.get("type") or "").strip().lower() == "quiz":
            m = {"type": "quiz", "question": row["text"], "options": [row[k] for k in "ABCD"],
                 "correct": "ABCD".index(row["correct"].strip().upper()), "explanation": row.get("explanation", "")}
        else:
            m = {"type": "text", "text": row["text"]}
        d["_m"].append((seq, m))
    out = []
    for d in days.values():
        d["morning"] = [m for _, m in sorted(d.pop("_m"), key=lambda x: x[0])]
        out.append(d)
    return sorted(out, key=lambda d: d["date"])


def get_plan(cfg):
    """Google Sheet (if configured) is the master copy; plan.json in the repo is the fallback."""
    local = load(PLAN, []) or []
    url = (cfg or {}).get("plan_sheet_csv", "").strip()
    if not url:
        return local
    try:
        sheet = sheet_plan(url)
        dates = {d["date"] for d in sheet}
        print(f"Plan: {len(sheet)} days from Google Sheet (+ repo plan.json as fallback).")
        os.environ["PLAN_SOURCE"] = f"Google Sheet ({len(sheet)} days)"
        return sorted(sheet + [d for d in local if d["date"] not in dates], key=lambda d: d["date"])
    except Exception as err:
        print(f"Could not read Google Sheet ({err}); using repo plan.json.")
        return local


def day_for(plan, date):
    return next((d for d in plan if d["date"] == date), None)


def send_item(t, m, cfg):
    if m["type"] == "text":
        return api("sendMessage", **t, text=m["text"], disable_web_page_preview=True)["message_id"]
    return api("sendPoll", **t, question=m["question"], options=[{"text": o} for o in m["options"]],
               is_anonymous=cfg.get("anonymous_polls", True), type="quiz",
               correct_option_id=m["correct"], explanation=(m.get("explanation") or "")[:200] or None)["message_id"]


def split(text, limit=4000):
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if cur and len(cur) + len(block) + 2 > limit:
            parts.append(cur)
            cur = block
        else:
            cur = f"{cur}\n\n{block}" if cur else block
    parts.append(cur)
    return parts


def do_post():
    cfg = load(CONFIG); plan = get_plan(cfg)
    state = load(STATE, {"days": {}})
    date = today()
    if date < cfg.get("start_date", "0000"):
        print(f"{date}: before start_date {cfg['start_date']} (Telegram schedule covers it). Nothing posted.")
        return
    day = day_for(plan, date)
    if not day:
        print(f"{date}: no CA Final day in plan.json. Nothing posted.")
        return
    st = state["days"].setdefault(date, {"day": day["day"], "sent": 0, "polls": []})
    t = target(cfg)
    if st["sent"] >= len(day["morning"]):
        print(f"{date}: Day {day['day']} already posted.")
        return
    for i in range(st["sent"], len(day["morning"])):
        m = day["morning"][i]
        mid = send_item(t, m, cfg)
        if i == 0:
            st["head"] = mid
        if m["type"] == "quiz":
            st["polls"].append({"id": mid, "correct": m["correct"]})
        st["sent"] = i + 1
        save(STATE, state)  # progress after every message: a re-run resumes here, no duplicates
        time.sleep(1)
    print(f"{date}: posted Day {day['day']} ({len(day['morning'])} messages).")


def do_answers():
    cfg = load(CONFIG); plan = get_plan(cfg)
    state = load(STATE, {"days": {}})
    date = today()
    day = day_for(plan, date)
    st = state["days"].get(date)
    if not day or not st:
        print(f"{date}: nothing was posted by the bot today. No answers to post.")
        return
    if st.get("answered"):
        print(f"{date}: answers already posted.")
        return
    t = target(cfg)
    stats = []
    for n, p in enumerate(st["polls"], 1):
        try:
            poll = api("stopPoll", chat_id=t["chat_id"], message_id=p["id"])
            tot = poll.get("total_voter_count", 0)
            ok = poll["options"][p["correct"]]["voter_count"]
            stats.append(f"Q{n}: {round(100 * ok / tot)}% correct ({tot} votes)" if tot else f"Q{n}: no votes")
        except RuntimeError as err:
            print(f"Could not close poll {p['id']}: {err}")
    text = day["evening"]
    if stats:
        text += "\n\n📊 How the group did: " + " · ".join(stats)
    text += "\n\n🔥 Next set tomorrow at 10:30 AM. Keep practising!"
    for part in split(text):
        api("sendMessage", **t, text=part, disable_web_page_preview=True,
            reply_parameters={"message_id": st.get("head"), "allow_sending_without_reply": True} if st.get("head") else None)
    st["answered"] = True
    save(STATE, state)
    print(f"{date}: posted answers for Day {day['day']}.")


def do_preview():
    plan = get_plan(load(CONFIG))
    day = day_for(plan, today())
    if not day:
        print("No day for", today())
        return
    for m in day["morning"]:
        if m["type"] == "text":
            print(m["text"], "\n")
        else:
            print("[POLL]", m["question"])
            for k, o in enumerate(m["options"]):
                print(f"   {'ABCD'[k]}. {o}{'  <-- correct' if k == m['correct'] else ''}")
            print("   💡", m.get("explanation", ""), "\n")
    print("--- 8:30 PM ---\n" + day["evening"])


def do_test():
    if not os.environ.get("TEST_CHAT", "").strip():
        sys.exit("TEST_CHAT is not set.")
    cfg = load(CONFIG); plan = get_plan(cfg)
    date = today()
    day = day_for(plan, date) or next((d for d in plan if d["date"] >= date), None)
    if not day:
        sys.exit("No day found.")
    t = target(cfg)
    for m in day["morning"]:
        send_item(t, m, cfg)
        time.sleep(1)
    for part in split(day["evening"]):
        api("sendMessage", **t, text=part)
    api("sendMessage", **t, text=f"🧪 Test OK – Day {day['day']} ({day['date']}). Plan source: {os.environ.get('PLAN_SOURCE', 'repo plan.json')}")
    print(f"Test: sent Day {day['day']} ({day['date']}) to the test group.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    {"post": do_post, "answers": do_answers, "preview": do_preview, "test": do_test}[mode]()
