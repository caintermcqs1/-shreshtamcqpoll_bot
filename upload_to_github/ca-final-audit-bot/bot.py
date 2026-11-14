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
import json, os, sys, time, urllib.request, urllib.error
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
    cfg, plan = load(CONFIG), load(PLAN)
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
    cfg, plan = load(CONFIG), load(PLAN)
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
    plan = load(PLAN)
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
    cfg, plan = load(CONFIG), load(PLAN)
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
    print(f"Test: sent Day {day['day']} ({day['date']}) to the test group.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    {"post": do_post, "answers": do_answers, "preview": do_preview, "test": do_test}[mode]()
